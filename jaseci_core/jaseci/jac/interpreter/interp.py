"""
Interpreter for jac code in AST form

This interpreter should be inhereted from the class that manages state
referenced through self.
"""
from jaseci.utils.utils import is_jsonable
from jaseci.element.element import element
from jaseci.graph.node import node
from jaseci.graph.edge import edge
from jaseci.attr.action import action
from jaseci.jac.jac_set import jac_set
from jaseci.jac.ir.jac_code import jac_ast_to_ir, jac_ir_to_ast
from jaseci.jac.machine.jac_scope import jac_scope
from jaseci.jac.machine.machine_state import machine_state

from jaseci.jac.machine.jac_scope import ctx_value


class interp(machine_state):
    """Shared interpreter class across both sentinels and walkers"""

    def run_attr_stmt(self, jac_ast, obj):
        """
        attr_stmt: has_stmt | can_stmt;
        """
        kid = jac_ast.kid
        if(kid[0].name == 'has_stmt'):
            self.run_has_stmt(kid[0], obj)
        elif(kid[0].name == 'can_stmt'):
            self.run_can_stmt(kid[0], obj)

    def run_has_stmt(self, jac_ast, obj):
        """
        has_stmt:
                KW_HAS KW_PRIVATE? KW_ANCHOR? has_assign
                (COMMA has_assign)* SEMI;
        """
        kid = jac_ast.kid
        kid = kid[1:]
        is_private = False
        is_anchor = False
        while True:
            if(kid[0].name == 'KW_PRIVATE'):
                kid = kid[1:]
                is_private = True
            if(kid[0].name == 'KW_ANCHOR'):
                kid = kid[1:]
                is_anchor = True
            self.run_has_assign(kid[0], obj, is_private, is_anchor)
            kid = kid[1:]
            if(not len(kid) or kid[0].name != 'COMMA'):
                break
            else:
                kid = kid[1:]

    def run_has_assign(self, jac_ast, obj, is_private, is_anchor):
        """
        has_assign: NAME | NAME EQ expression;
        """
        kid = jac_ast.kid
        var_name = kid[0].token_text()
        var_val = ""
        if(len(kid) > 1):
            var_val = self.run_expression(kid[2]).value
        if(is_anchor):
            if('anchor' in dir(obj)):
                if(obj.anchor is None):
                    obj.anchor = var_name
            else:
                self.rt_error('anchors not allowed for this type',
                              kid[0])

        if(var_name == '_private'):
            self.rt_error(
                f'Has variable name of `_private` not allowed!', kid[0])
        elif (var_name not in obj.context.keys()):  # Runs only once
            ctx_value(ctx=obj.context, name=var_name, value=var_val).write()
        if(is_private):
            if('_private' in obj.context.keys()):
                if(var_name not in obj.context['_private']):
                    obj.context['_private'].append(var_name)
            else:
                obj.context['_private'] = [var_name]

    def run_can_stmt(self, jac_ast, obj):
        """
        can_stmt:
            KW_CAN dotted_name (preset_in_out event_clause)? (
                COMMA dotted_name (preset_in_out event_clause)?
            )* SEMI
            | KW_CAN NAME event_clause? code_block;

        """
        kid = jac_ast.kid
        kid = kid[1:]
        while True:
            action_type = 'activity'
            access_list = None
            preset_in_out = None
            if (kid[0].name == 'NAME'):
                action_name = kid[0].token_text()
            else:
                action_name = self.run_dotted_name(kid[0])
            kid = kid[1:]
            if(len(kid) > 0 and kid[0].name == 'preset_in_out'):
                preset_in_out = jac_ast_to_ir(kid[0])
                kid = kid[1:]
            if(len(kid) > 0 and kid[0].name == 'event_clause'):
                action_type, access_list = self.run_event_clause(kid[0])
                kid = kid[1:]
            if (not isinstance(obj, node) and action_type != 'activity'):
                self.rt_warn(
                    "Only nodes can have on entry/exit, treating as activity",
                    kid[0])
                action_type = 'activity'
            if (kid[0].name == 'code_block'):
                getattr(obj, f"{action_type}_action_ids").add_obj(
                    action(
                        m_id=self._m_id,
                        h=self._h,
                        name=action_name,
                        value=jac_ast_to_ir(kid[0]),
                        preset_in_out=preset_in_out,
                        access_list=access_list
                    )
                )
                break
            else:
                func_link = \
                    self.get_builtin_action(action_name, jac_ast)
                if(func_link):
                    getattr(obj, f"{action_type}_action_ids").add_obj(
                        action(
                            m_id=self._m_id,
                            h=self._h,
                            name=action_name,
                            value=func_link,
                            preset_in_out=preset_in_out,
                            access_list=access_list
                        )
                    )
            if(not len(kid) or kid[0].name != 'COMMA'):
                break
            else:
                kid = kid[1:]

    def run_event_clause(self, jac_ast):
        """
        event_clause:
                KW_WITH name_list? (KW_ENTRY | KW_EXIT | KW_ACTIVITY);
        """
        kid = jac_ast.kid
        nl = []
        if(kid[1].name == "name_list"):
            nl = self.run_name_list(kid[1])
        return kid[-1].token_text(), nl

    def run_code_block(self, jac_ast):
        """
        code_block: LBRACE statement* RBRACE | COLON statement;
        TODO: Handle breaks and continues
        """
        kid = jac_ast.kid
        for i in kid:
            if (self._loop_ctrl):
                if (self._loop_ctrl == 'continue'):
                    self._loop_ctrl = None
                return
            if(i.name == 'statement'):
                self.run_statement(jac_ast=i)

    def run_node_ctx_block(self, jac_ast):
        """
        node_ctx_block: name_list code_block;
        """
        kid = jac_ast.kid
        for i in self.run_name_list(kid[0]):
            if (self.current_node.name == i):
                self.run_code_block(kid[1])
                return

    def run_statement(self, jac_ast):
        """
        statement:
            code_block
            | node_ctx_block
            | expression SEMI
            | if_stmt
            | for_stmt
            | while_stmt
            | ctrl_stmt SEMI
            | report_action
            | walker_action;
        """
        if (self._stopped):
            return
        kid = jac_ast.kid
        if(not hasattr(self, f'run_{kid[0].name}')):
            self.rt_error(
                f'This scope cannot execute the statement '
                f'"{kid[0].get_text()}" of type {kid[0].name}',
                kid[0])
            return
        stmt_func = getattr(self, f'run_{kid[0].name}')
        stmt_func(kid[0])

    def run_if_stmt(self, jac_ast):
        """
        if_stmt: KW_IF expression code_block (elif_stmt)* (else_stmt)?;
        """
        kid = jac_ast.kid
        if(self.run_expression(kid[1]).value):
            self.run_code_block(kid[2])
            return
        kid = kid[3:]
        if(len(kid)):
            while True:
                if(kid[0].name == 'elif_stmt'):
                    if(self.run_elif_stmt(kid[0])):
                        return
                elif(kid[0].name == 'else_stmt'):
                    self.run_else_stmt(kid[0])
                    return
                kid = kid[1:]
                if(not len(kid)):
                    break

    def run_elif_stmt(self, jac_ast):
        """
        elif_stmt: KW_ELIF expression code_block;
        """
        kid = jac_ast.kid
        if(self.run_expression(kid[1]).value):
            self.run_code_block(kid[2])
            return True
        else:
            return False

    def run_else_stmt(self, jac_ast):
        """
        else_stmt: KW_ELSE code_block;
        """
        kid = jac_ast.kid
        self.run_code_block(kid[1])

    def run_for_stmt(self, jac_ast):
        """
        for_stmt:
            KW_FOR expression KW_TO expression KW_BY expression code_block
            | KW_FOR NAME KW_IN expression code_block;
        """
        kid = jac_ast.kid
        loops = 0
        if(kid[1].name == 'expression'):
            self.run_expression(kid[1])
            while self.run_expression(kid[3]).value:
                self.run_code_block(kid[6])
                loops += 1
                if (self._loop_ctrl == 'break'):
                    self._loop_ctrl = None
                    break
                self.run_expression(kid[5])
                if(loops > self._loop_limit):
                    self.rt_error(f'Hit loop limit, breaking...', kid[0])
        else:
            var = self._jac_scope.get_live_var(
                kid[1].token_text(), create_mode=True)
            lst = self.run_expression(kid[3]).value
            # should check that lst is list here
            if(not isinstance(lst, list)):
                self.rt_error('Not a list for iteration!', kid[3])
            for i in lst:
                var.value = i
                var.write()
                self.run_code_block(kid[4])
                loops += 1
                if (self._loop_ctrl == 'break'):
                    self._loop_ctrl = None
                    break
                if(loops > self._loop_limit):
                    self.rt_error(f'Hit loop limit, breaking...', kid[0])

    def run_while_stmt(self, jac_ast):
        """
        while_stmt: KW_WHILE expression code_block;
        """
        kid = jac_ast.kid
        loops = 0
        while self.run_expression(kid[1]).value:
            self.run_code_block(kid[2])
            loops += 1
            if (self._loop_ctrl == 'break'):
                self._loop_ctrl = None
                break
            if(loops > self._loop_limit):
                self.rt_error(f'Hit loop limit, breaking...', kid[0])

    def run_ctrl_stmt(self, jac_ast):
        """
        ctrl_stmt: KW_CONTINUE | KW_BREAK | KW_SKIP;
        """
        kid = jac_ast.kid
        if (kid[0].name == 'KW_SKIP'):
            self._stopped = 'skip'
        elif (kid[0].name == 'KW_BREAK'):
            self._loop_ctrl = 'break'
        elif (kid[0].name == 'KW_CONTINUE'):
            self._loop_ctrl = 'continue'

    def run_report_action(self, jac_ast):
        """
        report_action: KW_REPORT expression SEMI;
        """
        kid = jac_ast.kid
        report = self.run_expression(kid[1]).value
        report = self.report_deep_serialize(report)
        if(not is_jsonable(report)):
            self.rt_error(f'Report not Json serializable', kid[0])
        self.report.append(report)

    def run_expression(self, jac_ast):
        """
        expression: connect (assignment | copy_assign | inc_assign)?;
        """
        kid = jac_ast.kid
        if(len(kid) > 1):
            if(kid[1].name == "assignment"):
                self._assign_mode = True
                dest = self.run_connect(kid[0])
                self._assign_mode = False
                return self.run_assignment(kid[1], dest=dest)
            elif(kid[1].name == "copy_assign"):
                dest = self.run_connect(kid[0])
                return self.run_copy_assign(kid[1], dest=dest)
            elif(kid[1].name == "inc_assign"):
                dest = self.run_connect(kid[0])
                return self.run_inc_assign(kid[1], dest=dest)
        else:
            return self.run_connect(kid[0])

    def run_assignment(self, jac_ast, dest):
        """
        assignment: EQ expression;
        """
        kid = jac_ast.kid
        result = self.run_expression(kid[1])
        dest.value = result.value
        dest.write()
        return dest

    def run_copy_assign(self, jac_ast, dest):
        """
        copy_assign: CPY_EQ expression;
        """
        kid = jac_ast.kid
        src = self.run_expression(kid[1])
        if (not self.rt_check_type(dest.value, [node, edge], kid[1])):
            self.rt_error("':=' only applies to nodes and edges", kid[1])
            return dest
        if (dest.value.name != src.value.name):
            self.rt_error(
                f"Node/edge arch {dest.value} don't "
                f"match {src.value}!", kid[1])
            return dest
        for i in src.value.context.keys():
            if(i in dest.value.context.keys()):
                ctx_value(ctx=dest.value.context, name=i,
                          value=src.value.context[i]).write()
        return dest

    def run_inc_assign(self, jac_ast, dest):
        """
        inc_assign: (PEQ | MEQ | TEQ | DEQ) expression;
        """
        kid = jac_ast.kid
        if(kid[0].name == 'PEQ'):
            dest.value = dest.value + self.run_expression(kid[1]).value
        elif(kid[0].name == 'MEQ'):
            dest.value = dest.value - self.run_expression(kid[1]).value
        elif(kid[0].name == 'TEQ'):
            dest.value = dest.value * self.run_expression(kid[1]).value
        elif(kid[0].name == 'DEQ'):
            dest.value = dest.value / self.run_expression(kid[1]).value
        dest.write()
        return dest

    def run_connect(self, jac_ast):
        """
        connect: logical ( (NOT)? edge_ref expression)?;
        """
        kid = jac_ast.kid
        if (len(kid) < 2):
            return self.run_logical(kid[0])
        bret = self.run_logical(kid[0])
        base = bret.value
        tret = self.run_expression(kid[-1])
        target = tret.value
        self.rt_check_type(base, [node, jac_set], kid[0])
        self.rt_check_type(target, [node, jac_set], kid[-1])
        if(isinstance(base, node)):
            base = jac_set(parent_obj=self, in_list=[base.jid])
        if(isinstance(target, node)):
            target = jac_set(parent_obj=self, in_list=[target.jid])
        if (kid[1].name == 'NOT'):
            for i in target.obj_list():
                for j in base.obj_list():
                    j.detach_edges(i, self.run_edge_ref(kid[2]).obj_list())
            return bret
        else:
            direction = kid[1].kid[0].name
            for i in target.obj_list():
                for j in base.obj_list():
                    use_edge = self.run_edge_ref(kid[1], is_spawn=True)
                    if (direction == 'edge_from'):
                        j.attach_inbound(i, [use_edge])
                    elif (direction == 'edge_to'):
                        j.attach_outbound(i, [use_edge])
                    else:
                        j.attach_bidirected(i, [use_edge])
        return tret

    def run_logical(self, jac_ast):
        """
        logical: compare ((KW_AND | KW_OR) compare)*;
        """
        kid = jac_ast.kid
        result = self.run_compare(kid[0])
        kid = kid[1:]
        while (kid):
            if (kid[0].name == 'KW_AND'):
                if (result):
                    result.value = result.value and self.run_compare(
                        kid[1]).value
            elif (kid[0].name == 'KW_OR'):
                if (not result):
                    result.value = result.value or self.run_compare(
                        kid[1]).value
            kid = kid[2:]
            if(not kid):
                break
        return result

    def run_compare(self, jac_ast):
        """
        compare: NOT compare | arithmetic (cmp_op arithmetic)*;
        """
        kid = jac_ast.kid
        if(kid[0].name == 'NOT'):
            return ctx_value(value=not self.run_compare(kid[1]).value)
        else:
            result = self.run_arithmetic(kid[0])
            kid = kid[1:]
            while (kid):
                other_res = self.run_arithmetic(kid[1])
                result = self.run_cmp_op(
                    kid[0], result, other_res)
                kid = kid[2:]
                if(not kid):
                    break
            return result

    def run_cmp_op(self, jac_ast, val1, val2):
        """
        cmp_op: EE | LT | GT | LTE | GTE | NE | KW_IN | nin;
        """
        kid = jac_ast.kid
        if(kid[0].name == 'EE'):
            return ctx_value(value=val1.value == val2.value)
        elif(kid[0].name == 'LT'):
            return ctx_value(value=val1.value < val2.value)
        elif(kid[0].name == 'GT'):
            return ctx_value(value=val1.value > val2.value)
        elif(kid[0].name == 'LTE'):
            return ctx_value(value=val1.value <= val2.value)
        elif(kid[0].name == 'GTE'):
            return ctx_value(value=val1.value >= val2.value)
        elif(kid[0].name == 'NE'):
            return ctx_value(value=val1.value != val2.value)
        elif(kid[0].name == 'KW_IN'):
            return ctx_value(value=val1.value in val2.value)
        elif(kid[0].name == 'nin'):
            return ctx_value(value=val1.value not in val2.value)

    def run_arithmetic(self, jac_ast):
        """
        arithmetic: term ((PLUS | MINUS) term)*;
        """
        kid = jac_ast.kid
        result = self.run_term(kid[0])
        kid = kid[1:]
        while (kid):
            other_res = self.run_term(kid[1])
            if(kid[0].name == 'PLUS'):
                result.value = result.value + other_res.value
            elif(kid[0].name == 'MINUS'):
                result.value = result.value - other_res.value
            kid = kid[2:]
            if(not kid):
                break
        return result

    def run_term(self, jac_ast):
        """
        term: factor ((MUL | DIV | MOD) factor)*;
        """
        kid = jac_ast.kid
        result = self.run_factor(kid[0])
        kid = kid[1:]
        while (kid):
            other_res = self.run_factor(kid[1])
            if(kid[0].name == 'MUL'):
                result.value = result.value * other_res.value
            elif(kid[0].name == 'DIV'):
                result.value = result.value / other_res.value
            elif(kid[0].name == 'MOD'):
                result.value = result.value % other_res.value
            kid = kid[2:]
            if(not kid):
                break
        return result

    def run_factor(self, jac_ast):
        """
        factor: (PLUS | MINUS) factor | power;
        """
        kid = jac_ast.kid
        if(kid[0].name == 'power'):
            return self.run_power(kid[0])
        else:
            result = self.run_factor(kid[1])
            if(kid[0].name == 'MINUS'):
                result.value = -(result.value)
            return result

    def run_power(self, jac_ast):
        """
        power: func_call (POW factor)*;
        """
        kid = jac_ast.kid
        result = self.run_func_call(kid[0])
        kid = kid[1:]
        if(len(kid) < 1):
            return result
        elif(kid[0].name == 'POW'):
            while (kid):
                result.value = result.value ** self.run_factor(kid[1]).value
                kid = kid[2:]
                if(not kid):
                    break
            return result

    def run_func_call(self, jac_ast):
        """
        func_call:
            atom (LPAREN expr_list? RPAREN)?
            | atom? DBL_COLON NAME spawn_ctx?;
        """
        kid = jac_ast.kid
        atom_res = ctx_value(value=self._jac_scope.has_obj)
        if (kid[0].name == 'atom'):
            atom_res = self.run_atom(kid[0])
            kid = kid[1:]
        if(len(kid) < 1):
            return atom_res

        elif (kid[0].name == 'DBL_COLON'):
            if(len(kid) > 2):
                self.run_spawn_ctx(kid[2], atom_res.value)
            self.call_ability(
                nd=atom_res.value,
                name=kid[1].token_text(),
                act_list=atom_res.value.activity_action_ids)
            return atom_res
        elif(kid[0].name == "LPAREN"):
            param_list = []
            if(kid[1].name == 'expr_list'):
                param_list = self.run_expr_list(kid[1]).value
            if (isinstance(atom_res.value, action)):
                return ctx_value(value=atom_res.value.trigger(param_list))
            else:
                self.rt_error(f'Unable to execute ability {atom_res}',
                              kid[0])

    def run_atom(self, jac_ast):
        """
        atom:
            INT
            | FLOAT
            | STRING
            | BOOL
            | array_ref
            | node_edge_ref
            | list_val
            | dotted_name
            | LPAREN expression RPAREN
            | spawn
            | atom DOT func_built_in
            | atom index+
            | DEREF expression;
        """
        kid = jac_ast.kid
        if(kid[0].name == 'INT'):
            return ctx_value(value=int(kid[0].token_text()))
        elif(kid[0].name == 'FLOAT'):
            return ctx_value(value=float(kid[0].token_text()))
        elif(kid[0].name == 'STRING'):
            return ctx_value(value=self.parse_str_token(kid[0].token_text()))
        elif(kid[0].name == 'BOOL'):
            return ctx_value(value=bool(kid[0].token_text() == 'true'))
        elif(kid[0].name == 'dotted_name'):
            return self._jac_scope.get_live_var(
                self.run_dotted_name(kid[0]),
                create_mode=self._assign_mode)
        elif(kid[0].name == 'LPAREN'):
            return self.run_expression(kid[1])
        elif(kid[0].name == 'atom'):
            atom_res = self.run_atom(kid[0])
            kid = kid[1:]
            if(kid[0].name == 'DOT'):
                return self.run_func_built_in(atom_res, kid[1])
            elif (kid[0].name == "index"):
                if(isinstance(atom_res.value, list) or
                   isinstance(atom_res.value, dict)):
                    for i in kid:
                        if(i.name == 'index'):
                            atom_res = ctx_value(
                                ctx=atom_res.value, name=self.run_index(i))
                    atom_res.value = self._jac_scope.reference_to_value(
                        atom_res.value)
                    return atom_res
                else:
                    self.rt_error(f'Cannot index into {atom_res}'
                                  f' of type {type(atom_res)}!',
                                  kid[0])
                    return None
        elif (kid[0].name == 'DEREF'):
            result = self.run_expression(kid[1])
            if (self.rt_check_type(result.value, element, kid[1])):
                result = ctx_value(value=result.value.jid)
            return result
        else:
            return getattr(self, f'run_{kid[0].name}')(kid[0])

    def run_func_built_in(self, atom_res, jac_ast):
        """
        func_built_in:
            | KW_LENGTH
            | KW_KEYS
            | KW_EDGE
            | KW_NODE
            | KW_CONTEXT
            | KW_INFO
            | KW_DETAILS
            | KW_DESTROY LPAREN expression RPAREN;
        """
        from jaseci.actor.walker import walker
        kid = jac_ast.kid
        if (kid[0].name == "KW_LENGTH"):
            if(isinstance(atom_res.value, list)):
                return ctx_value(value=len(atom_res.value))
            else:
                self.rt_error(
                    f'Cannot get length of {atom_res.value}. Not List!',
                    kid[0])
                return ctx_value(value=0)
        elif (kid[0].name == "KW_KEYS"):
            if(isinstance(atom_res.value, dict)):
                return ctx_value(value=atom_res.value.keys())
            else:
                self.rt_error(f'Cannot get keys of {atom_res}. '
                              f'Not Dictionary!', kid[0])
                return ctx_value(value=[])
        elif (kid[0].name == "KW_EDGE"):
            if(isinstance(atom_res.value, node)):
                return ctx_value(value=self.obj_set_to_jac_set(
                    self.current_node.attached_edges(atom_res.value)))
            elif(isinstance(atom_res.value, edge)):
                return atom_res
            elif(isinstance(atom_res.value, jac_set)):
                res = jac_set(self)
                for i in atom_res.value.obj_list():
                    if(isinstance(i, edge)):
                        res.add_obj(i)
                    elif(isinstance(i, node)):
                        res += self.obj_set_to_jac_set(
                            self.current_node.attached_edges(i))
                return ctx_value(value=res)
            else:
                self.rt_error(f'Cannot get edges from {atom_res.value}. '
                              f'Type {type(atom_res.value)} invalid', kid[0])
        # may want to remove 'here" node from return below
        elif (kid[0].name == "KW_NODE"):
            if(isinstance(atom_res.value, node)):
                return atom_res
            elif(isinstance(atom_res.value, edge)):
                return ctx_value(value=self.obj_set_to_jac_set(
                    atom_res.nodes()))
            elif(isinstance(atom_res.value, jac_set)):
                res = jac_set(self)
                for i in atom_res.value.obj_list():
                    if(isinstance(i, edge)):
                        res.add_obj(i.to_node())
                        res.add_obj(i.from_node())
                    elif(isinstance(i, node)):
                        res.add_obj(i)
                return ctx_value(value=res)
            else:
                self.rt_error(f'Cannot get edges from {atom_res}. '
                              f'Type {type(atom_res)} invalid', kid[0])
        elif (kid[0].name == "KW_CONTEXT"):
            if(self.rt_check_type(atom_res.value,
                                  [node, edge, walker], kid[0])):
                return ctx_value(value=atom_res.value.context)
        elif (kid[0].name == "KW_INFO"):
            if(self.rt_check_type(atom_res.value,
                                  [node, edge, walker], kid[0])):
                return ctx_value(
                    value=atom_res.value.serialize(detailed=False))
        elif (kid[0].name == "KW_DETAILS"):
            if(self.rt_check_type(atom_res.value,
                                  [node, edge, walker], kid[0])):
                return ctx_value(
                    value=atom_res.value.serialize(detailed=True))
        elif (kid[0].name == "KW_DESTROY"):
            idx = self.run_expression(kid[2])
            if (isinstance(atom_res.value, list) and
                    isinstance(idx.value, int)):
                del atom_res.value[idx.value]
                return atom_res
            else:
                self.rt_error(f'Cannot remove index {idx} from {atom_res}.',
                              kid[0])
        return atom_res

    def run_node_edge_ref(self, jac_ast):
        """
        node_edge_ref:
            node_ref filter_ctx?
            | edge_ref (node_ref filter_ctx?)?;
        """
        kid = jac_ast.kid

        if(kid[0].name == 'node_ref'):
            result = self.run_node_ref(kid[0])
            if(len(kid) > 1):
                result = self.run_filter_ctx(kid[1], result)
            return ctx_value(value=result)

        elif (kid[0].name == 'edge_ref'):
            result = self.edge_to_node_jac_set(self.run_edge_ref(kid[0]))
            if(len(kid) > 1 and kid[1].name == 'node_ref'):
                nres = self.run_node_ref(kid[1])
                if(len(kid) > 2):
                    nres = self.run_filter_ctx(kid[2], nres)
                result = result * nres
            return ctx_value(value=result)

    def run_node_ref(self, jac_ast, is_spawn=False):
        """
        node_ref: KW_NODE DBL_COLON NAME;
        """
        kid = jac_ast.kid
        if(not is_spawn):
            result = jac_set(self)
            if (len(kid) > 1):
                for i in self.viable_nodes().obj_list():
                    if (i.name == kid[2].token_text()):
                        result.add_obj(i)
            else:
                result += self.viable_nodes()
        else:
            if(len(kid) > 1):
                result = self.parent().run_architype(
                    kid[2].token_text(), kind='node', caller=self)
            else:
                result = node(m_id=self._m_id, h=self._h)
        return result

    def run_walker_ref(self, jac_ast):
        """
        walker_ref: KW_WALKER DBL_COLON NAME;
        """
        kid = jac_ast.kid
        return self.parent().spawn_walker(kid[2].token_text(), caller=self)

    def run_graph_ref(self, jac_ast):
        """
        graph_ref: KW_GRAPH DBL_COLON NAME;
        """
        kid = jac_ast.kid
        gph = self.parent().run_architype(
            kid[2].token_text(), kind='graph', caller=self)
        return gph

    def run_edge_ref(self, jac_ast, is_spawn=False):
        """
        edge_ref: edge_to | edge_from | edge_any;
        """
        kid = jac_ast.kid
        if(not is_spawn):
            expr_func = getattr(self, f'run_{kid[0].name}')
            return expr_func(kid[0])
        else:
            if(len(kid[0].kid) > 2):
                result = self.parent().run_architype(
                    kid[0].kid[2].token_text(), kind='edge',
                    caller=self)
                if(kid[0].kid[3].name == 'spawn_ctx'):
                    self.run_spawn_ctx(kid[0].kid[3], result)
                elif(kid[0].kid[3].name == 'filter_ctx'):
                    self.rt_error("Filtering not allowed here", kid[0].kid[3])
            else:
                result = edge(m_id=self._m_id, h=self._h,
                              kind='edge', name='generic')
            return result

    def run_edge_to(self, jac_ast):
        """
        edge_to:
            '-->'
            | '-' ('[' NAME (spawn_ctx | filter_ctx)? ']')? '->';
        """
        kid = jac_ast.kid
        result = jac_set(self)
        for i in self.current_node.outbound_edges() + \
                self.current_node.bidirected_edges():
            if (len(kid) > 2 and i.name != kid[2].token_text()):
                continue
            result.add_obj(i)
        if(len(kid) > 2 and kid[3].name == 'filter_ctx'):
            result = self.run_filter_ctx(kid[3], result)
        elif(len(kid) > 2 and kid[3].name == 'spawn_ctx'):
            self.rt_error("Assigning values not allowed here", kid[3])
        return result

    def run_edge_from(self, jac_ast):
        """
        edge_from:
            '<--'
            | '<-' ('[' NAME (spawn_ctx | filter_ctx)? ']')? '-';
        """
        kid = jac_ast.kid
        result = jac_set(self)
        for i in self.current_node.inbound_edges() + \
                self.current_node.bidirected_edges():
            if (len(kid) > 2 and i.name != kid[2].token_text()):
                continue
            result.add_obj(i)
        if(len(kid) > 2 and kid[3].name == 'filter_ctx'):
            result = self.run_filter_ctx(kid[3], result)
        elif(len(kid) > 2 and kid[3].name == 'spawn_ctx'):
            self.rt_error("Assigning values not allowed here", kid[3])
        return result

    def run_edge_any(self, jac_ast):
        """
        edge_any:
            '<-->'
            | '<-' ('[' NAME (spawn_ctx | filter_ctx)? ']')? '->';
        NOTE: these do not use strict bidirected semantic but any edge
        """
        kid = jac_ast.kid
        result = jac_set(self)
        for i in self.current_node.attached_edges():
            if (len(kid) > 2 and i.name != kid[2].token_text()):
                continue
            result.add_obj(i)
        if(len(kid) > 2 and kid[3].name == 'filter_ctx'):
            result = self.run_filter_ctx(kid[3], result)
        elif(len(kid) > 2 and kid[3].name == 'spawn_ctx'):
            self.rt_error("Assigning values not allowed here", kid[3])
        return result

    def run_list_val(self, jac_ast):
        """
        list_val: LSQUARE expr_list? RSQUARE;
        """
        kid = jac_ast.kid
        if(kid[1].name == "expr_list"):
            return self.run_expr_list(kid[1])
        return ctx_value(value=[])

    def run_index(self, jac_ast):
        """
        index: LSQUARE expression RSQUARE;
        """
        kid = jac_ast.kid
        idx = self.run_expression(kid[1]).value
        if(not isinstance(idx, int) and not isinstance(idx, str)):
            self.rt_error(f'Index of type {type(idx)} not valid. '
                          f'Indicies must be an integer or string!', kid[1])
            return None
        return idx

    def run_dict_val(self, jac_ast):
        """
        dict_val: LBRACE (kv_pair (COMMA kv_pair)*)? RBRACE;
        """
        kid = jac_ast.kid
        dict_res = {}
        for i in kid:
            if(i.name == 'kv_pair'):
                self.run_kv_pair(i, dict_res)
        return ctx_value(value=dict_res)

    def run_kv_pair(self, jac_ast, obj):
        """
        kv_pair: STRING COLON expression;
        """
        kid = jac_ast.kid
        obj[self.parse_str_token(kid[0].token_text())
            ] = self.run_expression(kid[2]).value

    def run_spawn(self, jac_ast):
        """
        spawn: KW_SPAWN expression spawn_object;

        NOTE: spawn statements support locations that are either nodes or
        jac_sets
        """
        kid = jac_ast.kid
        if(kid[1].name == 'expression'):
            location = self.run_expression(kid[1]).value
            if(isinstance(location, node)):
                return self.run_spawn_object(kid[2], location)
            elif(isinstance(location, jac_set)):
                res = []
                for i in location.obj_list():
                    res.append(self.run_spawn_object(kid[2], i))
                return ctx_value(value=res)
            else:
                self.rt_error(
                    f'Spawn can not occur on {type(location)}!', kid[1])
        else:
            return self.run_spawn_object(kid[1], None)

    def run_spawn_object(self, jac_ast, location):
        """
        spawn_object: node_spawn | walker_spawn;
        """
        kid = jac_ast.kid
        expr_func = getattr(self, f'run_{kid[0].name}')
        return expr_func(kid[0], location)

    def run_node_spawn(self, jac_ast, location):
        """
        node_spawn: edge_ref? node_ref spawn_ctx?;
        """
        kid = jac_ast.kid
        if(kid[0].name == 'node_ref'):
            ret_node = self.run_node_ref(kid[0], is_spawn=True)
        else:
            use_edge = self.run_edge_ref(kid[0], is_spawn=True)
            ret_node = self.run_node_ref(kid[1], is_spawn=True)
            direction = kid[0].kid[0].name
            if (direction == 'edge_from'):
                location.attach_inbound(ret_node, [use_edge])
            elif (direction == 'edge_to'):
                location.attach_outbound(ret_node, [use_edge])
            else:
                location.attach_bidirected(ret_node, [use_edge])
        if (kid[-1].name == 'spawn_ctx'):
            self.run_spawn_ctx(kid[-1], ret_node)
        return ctx_value(value=ret_node)

    def run_walker_spawn(self, jac_ast, location):
        """
        walker_spawn: walker_ref spawn_ctx?;
        """
        kid = jac_ast.kid
        walk = self.run_walker_ref(kid[0])
        walk.prime(location)
        if(len(kid) > 1):
            self.run_spawn_ctx(kid[1], walk)
        walk.run()
        ret = self._jac_scope.reference_to_value(walk.anchor_value())
        self.report = self.report + walk.report
        walk.destroy()
        return ctx_value(value=ret)

    def run_graph_spawn(self, jac_ast, location):
        """
        graph_spawn: edge_ref graph_ref;
        """
        kid = jac_ast.kid
        use_edge = self.run_edge_ref(kid[0], is_spawn=True)
        result = self.run_graph_ref(kid[1])
        direction = kid[0].kid[0].name
        if (direction == 'edge_from'):
            location.attach_inbound(result, [use_edge])
        elif (direction == 'edge_to'):
            location.attach_outbound(result, [use_edge])
        else:
            location.attach_bidirected(result, [use_edge])
        return ctx_value(value=result)

    def run_spawn_ctx(self, jac_ast, obj):
        """
        spawn_ctx: LPAREN (spawn_assign (COMMA spawn_assign)*)? RPAREN;
        """
        kid = jac_ast.kid
        for i in kid:
            if (i.name == 'spawn_assign'):
                self.run_spawn_assign(i, obj)

    def run_filter_ctx(self, jac_ast, obj):
        """
        filter_ctx:
                LPAREN (filter_compare (COMMA filter_compare)*)? RPAREN;
        """
        kid = jac_ast.kid
        ret = jac_set(self)
        for i in obj.obj_list():
            for j in kid:
                if (j.name == 'filter_compare'):
                    if(self.run_filter_compare(j, i)):
                        ret.add_obj(i)
        return ret

    def run_spawn_assign(self, jac_ast, obj):
        """
        spawn_assign: NAME EQ expression;
        """
        kid = jac_ast.kid
        name = kid[0].token_text()
        if(name in obj.context.keys() or obj.j_type == 'walker'):
            result = self.run_expression(kid[-1]).value
            ctx_value(ctx=obj.context, name=name, value=result).write()
        else:
            self.rt_error(f'{name} not present in object', kid[0])

    def run_filter_compare(self, jac_ast, obj):
        """
        filter_compare: NAME cmp_op expression;
        """
        kid = jac_ast.kid
        name = kid[0].token_text()
        if(name in obj.context.keys()):
            result = self.run_expression(kid[-1])
            return self.run_cmp_op(
                kid[1], ctx_value(ctx=obj.context, name=name),
                result).value
        else:
            self.rt_error(f'{name} not present in object', kid[0])
            return False

    def run_dotted_name(self, jac_ast):
        """
        dotted_name: NAME (DOT NAME)*;
        """
        kid = jac_ast.kid
        ret = ''
        for i in kid:
            if(i.name == 'NAME'):
                ret += i.token_text()
                if(i == kid[-1]):
                    break
                ret += '.'
        return ret

    def run_name_list(self, jac_ast):
        """
        name_list: NAME (COMMA NAME)*;
        """
        kid = jac_ast.kid
        ret = []
        for i in kid:
            if(i.name == 'NAME'):
                ret.append(i.token_text())
        return ret

    def run_expr_list(self, jac_ast):
        """
        expr_list: expression (COMMA expression)*;
        """
        kid = jac_ast.kid
        ret = []
        for i in kid:
            if(i.name == 'expression'):
                ret.append(self.run_expression(i).value)
        return ctx_value(value=ret)

    # Helper Functions ##################
    def call_ability(self, nd, name, act_list):
        m = interp(parent_override=self.parent(), m_id=self._m_id)
        m.push_scope(jac_scope(parent=nd,
                               has_obj=nd,
                               action_sets=[nd.activity_action_ids]))
        m._jac_scope.inherit_agent_refs(self._jac_scope)
        m.run_code_block(jac_ir_to_ast(
            act_list.get_obj_by_name(name).value))
        self.report = self.report + m.report

    def report_deep_serialize(self, report):
        """Performs JSON serialization for lists of lists of lists etc"""
        if (isinstance(report, element)):
            report = report.serialize()
        elif (isinstance(report, jac_set)):
            blobs = []
            for i in report.obj_list():
                blobs.append(i.serialize())
            report = blobs
        elif (isinstance(report, list)):
            blobs = []
            for i in report:
                blobs.append(self.report_deep_serialize(i))
            report = blobs
        return report
