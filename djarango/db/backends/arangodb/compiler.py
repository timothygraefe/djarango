#
# compiler.py
#
# Timothy Graefe, Javamata LLC, Nov 2021
#

import logging
import json
from typing import List
from itertools import chain
from enum import Enum, auto

from django.core.exceptions import EmptyResultSet
from django.db import DatabaseError
from django.db import IntegrityError
from django.db.models import NOT_PROVIDED
from django.db.models.lookups import IsNull, In, BuiltinLookup
from django.db.models.expressions import Col
from django.db.models.sql import compiler
from django.db.models.sql.datastructures import Join
from django.db.models.sql.where import WhereNode, AND
from django.db.models.sql.constants import (
        CURSOR, GET_ITERATOR_CHUNK_SIZE, MULTI, NO_RESULTS, ORDER_DIR, SINGLE)
from django.db.transaction import TransactionManagementError

logger = logging.getLogger('django.db.backends.arangodb')

class AQLQueryContext(Enum):
    AQL_QUERY           = auto()
    AQL_QUERY_INSERT    = auto()
    AQL_QUERY_DELETE    = auto()
    AQL_QUERY_UPDATE    = auto()

################################################################################
#
# SQL Compiler Overrides
#
# The base compiler class allows the vendor to override the as_sql() method for
# all types of SQL node classes.  The functions below are overridden:
#
#   Col.as_sql()
#   Join.as_sql()
#   Where.as_sql()
#   IsNull.as_sql()
#
################################################################################

################################################################################
#
#   Notes about column aliases:
#   ArangoDB uses a "FOR" loop paradigm for the equivalent SQL "SELECT".
#   E.g.:
#       SQL: > SELECT * FROM mytable;
#       AQL: > FOR myrec IN mytable RETURN myrec
#
#   There is always a loop variable (similar to column alias) in all AQL queries.
#
#   A conventional AQL alias is implemented in the "RETURN" part of the AQL:
#       SQL: >  SELECT "mytable"."myfield" AS "myrec" FROM "mytable" \
#                   WHERE "mytable"."myfield" = "pattern_data" LIMIT 1
#       AQL: >  FOR myrec IN mytable
#                   FILTER myrec.myfield == "pattern_data"
#                       RETURN { myuser: myrec.myfield }
#
################################################################################

################################################################################
# Override the Col node class so it returns the column formatted for AQL.
################################################################################
def override_col_as_sql(self, compiler, connection) -> (str, List):

    loop_alias = compiler.get_aql_loop_alias(self.alias)

    # Use _key element of ArangoDB documents as the Django model id (primary key)
    if self.target.column == 'id':
        return "%s.%s" % (loop_alias, '_key'), []

    return "%s.%s" % (loop_alias, self.target.column), []

# Override the Col.as_sql() method with code above.
setattr(Col, 'as_arangodb', override_col_as_sql)

################################################################################
#
# AQL uses nested loops instead of 'INNER JOIN' syntax.
# Code below adapted from db/models/sql/datastructures.py to support AQL.
#
# FROM/INNER JOIN" equivalent:
#   FOR v1 in t1 FOR v2 in t2 FILTER t1.v1 == t2.v2
#
################################################################################
def override_join_as_sql(self, compiler, connection) -> (str, List):
    """
    Responsible for (sql, [params]) tuple to be included in the current query.
    Generate the full
       LEFT OUTER JOIN sometable ON sometable.somecol = othertable.othercol, params
    clause for this join.
    """

    join_conditions = []
    params          = []

    qn = compiler.quote_name_unless_alias
    qn2 = connection.ops.quote_name

    # Add a join condition for each pair of joining columns.
    for lhs_col, rhs_col in self.join_cols:
        test = qn(lhs_col)
        test = qn2(rhs_col)

        if lhs_col == 'id':
            lhs_col = '_key'
        if rhs_col == 'id':
            rhs_col = '_key'
        t1 = (self.parent_alias)
        t2 = (self.table_alias)
        var1 = compiler.get_aql_loop_alias(t1)
        var2 = compiler.get_aql_loop_alias(t2)
        aql_join = f"FOR {var1} in {t1} FOR {var2} in {t2} FILTER {var1}.{lhs_col} == {var2}.{rhs_col}"
        join_conditions.append(aql_join)

    # Add a single condition inside parentheses for whatever
    # get_extra_restriction() returns.
    extra_cond = self.join_field.get_extra_restriction(
        compiler.query.where_class, self.table_alias, self.parent_alias)
    if extra_cond:
        extra_sql, extra_params = compiler.compile(extra_cond)
        join_conditions.append('(%s)' % extra_sql)
        params.extend(extra_params)

    if self.filtered_relation:
        extra_sql, extra_params = compiler.compile(self.filtered_relation)
        if extra_sql:
            join_conditions.append('(%s)' % extra_sql)
            params.extend(extra_params)

    if not join_conditions:
        # This might be a rel on the other end of an actual declared field.
        declared_field = getattr(self.join_field, 'field', self.join_field)
        raise ValueError(
            "Join generated an empty ON clause. %s did not yield either "
            "joining columns or extra restrictions." % declared_field.__class__
        )

    return ' '.join(join_conditions), params

# Override the Join.as_sql() method with function above.
setattr(Join, 'as_arangodb', override_join_as_sql)

################################################################################
#
# SQL 'SELECT' is equivalent to the AQL 'FOR' loop construct which uses loop
# variable(s) in a manner similar to SQL table aliases.  AQL loop variables are
# not preceded by the 'AS' keyword, as with SQL.
#
# AQL 'where' is accomplished via the AQL FILTER keyword; it must take into
# consideration any loop variables.  Negation is handled differently as well.
#
# Copied from db/models/sql/where.py and adapted to support AQL.
#
################################################################################
def override_where_as_sql(self, compiler, connection) -> (str, List):
    """
    Return the SQL version of the where clause and the value to be
    substituted in. Return '', [] if this node matches everything,
    None, [] if this node is empty, and raise EmptyResultSet if this
    node can't match anything.
    TTG - note that the syntax is different for "WHERE" in AQL, depending
        on wether it is a query, insert, delete, or update.
    """
    negated_operators = {
        'exact' : ('==', '!='),
        'gt'    : ('>',  '<='),
        'gte'   : ('>=', '<'),
        'lt'    : ('<',  '>='),
        'lte'   : ('<=', '>'),
    }

    result = []
    result_params = []

    if self.connector == AND:
        full_needed, empty_needed = len(self.children), 1
    else:
        full_needed, empty_needed = 1, len(self.children)

    for child in self.children:
        try:
            # The following does not fall through to a vendor implementation (ArangoDB),
            # but will invoke col_as_sql in a subsequent node compile.
            # It will return something like: <loop alias>.field IN ['<var 1>', ... ]
            # E.g., 'ta1.session_key IN (%s)', [ '<session key>' ]
            sql, params = compiler.compile(child)
        except EmptyResultSet:
            empty_needed -= 1
        else:
            if sql:
                # Parameters need to be single-quoted in the AQL, e.g.:
                #   ... FILTER item.app_label == 'admin' ...
                #   ... FILTER item.app_label == 'admin' AND item.model == 'model'
                if not "'%s'" in sql:
                    sql = sql.replace("%s", "'%s'")

                result.append(sql)
                result_params.extend(params)
            else:
                full_needed -= 1

        # Check if this node matches nothing or everything.
        # First check the amount of full nodes and empty nodes
        # to make this node empty/full.
        # Now, check if this node is full/empty using the
        # counts.
        if empty_needed == 0:
            if self.negated:
                return '', []
            else:
                raise EmptyResultSet
        if full_needed == 0:
            if self.negated:
                raise EmptyResultSet
            else:
                return '', []

    # If there are multiple FILTER conditions, they will be joined by the
    # self.connector keyword (in this case 'AND').  AQL can stack multiple
    # FILTER conditions with no connecting keyword, but within the FILTER
    # clause they are connected by 'AND' (self.connector is 'AND')
    conn = ' %s ' % self.connector
    sql_string = conn.join(result)
    if sql_string:
        if self.negated:
            # Some backends (Oracle at least) need parentheses
            # around the inner SQL in the negated case, even if the
            # inner SQL contains just a single expression.
            # AQL - self.negated is handled via negated_operators
            if child.lookup_name in negated_operators:
                sql_string = sql_string.replace(negated_operators[child.lookup_name][0],
                                                negated_operators[child.lookup_name][1])
            else:
                # The expression in sql_string must be enclosed within (), or
                # AQL will interpret the "NOT" keyword as bound to the first
                # element in the expression rather than the full expression.
                sql_string = 'NOT (%s)' % sql_string
        elif len(result) > 1 or self.resolved:
            # Do not use the [] brackets here.  Those are only to group a list
            # of parameters.  In this case, we are combining conditional tests.
            sql_string = '(%s)' % sql_string

    return sql_string, result_params

# Override the WhereNode.as_sql() method with code above.
setattr(WhereNode, 'as_arangodb', override_where_as_sql)

################################################################################
#
# Override IsNull to check for attributes in the document, via "HAS()"
#
################################################################################
def override_isnull_as_sql(self, compiler, connection) -> (str, List):
    sql, params = compiler.compile(self.lhs)

    if '.' in sql:
        alias = sql.split('.')[0]
        var   = sql.split('.')[1]
    else:
        alias = var = sql

    if self.rhs:
        sql_string = f"((NOT HAS({alias}, '{var}')) OR IS_NULL({sql}))"
    else:
        sql_string = f"(HAS({alias}, '{var}') AND (NOT IS_NULL({sql})))"

    return sql_string, params

# Override the IsNull.as_sql() method with code above.
setattr(IsNull, 'as_arangodb', override_isnull_as_sql)

################################################################################
#
# Override "In" node, to use [] in place of () for list of parameters
#
################################################################################
def override_in_as_sql(self, compiler, connection) -> (str, List):

    max_in_list_size = connection.ops.max_in_list_size()
    if self.rhs_is_direct_value() and max_in_list_size and len(self.rhs) > max_in_list_size:
        sql, params = self.split_parameter_list_as_sql(compiler, connection)
    else:
        sql, params = BuiltinLookup.as_sql(self, compiler, connection)

    # AQL uses [] brackets rather than () for lists of match values.
    sql = sql.replace("(", "[")
    sql = sql.replace(")", "]")
    return sql, params

# Override the In.as_sql() method with code above.
setattr(In, 'as_arangodb', override_in_as_sql)


################################################################################
#
# Override BuiltinLookup node; always enclose conditional expressions within () 
#
################################################################################
def override_builtinlookup_as_sql(self, compiler, connection) -> (str, List):

    lhs_sql, params = self.process_lhs(compiler, connection)
    rhs_sql, rhs_params = self.process_rhs(compiler, connection)
    params.extend(rhs_params)
    rhs_sql = self.get_rhs_op(connection, rhs_sql)
    return '(%s %s)' % (lhs_sql, rhs_sql), params

# Override the In.as_sql() method with code above.
setattr(BuiltinLookup, 'as_arangodb', override_builtinlookup_as_sql)

################################################################################
################################################################################

################################################################################
#
# SQLCompiler() provides .as_sql() to convert a query object to SQL (AQL in this
# case), and then .execute_sql() invokes the python-arango driver to fetch
# results from the DB.  A cursor should be used to iterate over the results.
#
################################################################################
class SQLCompiler(compiler.SQLCompiler):
    aql_query_context = AQLQueryContext.AQL_QUERY
    aql_loop_alias = {}

    def get_aql_loop_alias(self, table = None):
        AQL_TA_PREFIX = 'ta'
        if table is None:
            return AQL_TA_PREFIX

        if not table in self.aql_loop_alias:
            self.aql_loop_alias[table] = AQL_TA_PREFIX + str(len(self.aql_loop_alias))

        return self.aql_loop_alias[table]

    def as_sql(self, with_limits=True, with_col_aliases=False, subquery=False):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.

        If 'with_limits' is False, any limit/offset information is not included
        in the query.
        """
        # as_sql() converts the query into SQL in the target backend (in this case
        # it will be AQL for the ArangoDB).  Subsequently, the object will invoke
        # execute_sql(), which sends the properly constructed AQL to the DB engine.

        self.subquery = subquery
        refcounts_before = self.query.alias_refcount.copy()

        # Attempt to build an AQL query (a string), piece by piece.
        try:
            extra_select, order_by, group_by = self.pre_sql_setup()
            distinct_fields = self.get_distinct()

            # A "Join" is formed in get_from_clause() in SQLCompiler.
            from_, f_params = self.get_from_clause()

            # self.compile(self.where) invokes WhereNode.as_sql() for the "where" clause.
            where, w_params = self.compile(self.where) if self.where is not None else ("", [])
            having, h_params = self.compile(self.having) if self.having is not None else ("", [])

            # Start the query with "for item in <from_> ...".
            # "from_" should be the collection name
            params = []
            result = []

            loop_alias = self.get_aql_loop_alias()
            if from_:
                # If this query is a "join", the from_ clause will include nested loops.
                result = [ i for i in from_ if 'FOR' in i ]
                if not len(result) > 0:
                    # Not a join, just normal AQL "SELECT"
                    table = from_.pop(0)
                    loop_alias = self.get_aql_loop_alias(table)
                    result.extend(['FOR', loop_alias, 'IN'])
                    result.extend([table])

                    for table in from_:
                        loop_alias = self.get_aql_loop_alias(table)
                        result.extend(['AND', loop_alias, 'IN'])
                        result.extend([table])

            # Add a FILTER clause if SQL 'where' is present.
            if where:
                result.append('FILTER')
                where_partial = where % tuple(w_params)
                result.append(where_partial)
                params.extend(w_params)

            if self.query.distinct:
                result.append(self.connection.ops.distinct_sql(distinct_fields))

            # AQL ORDER of results is accomplished via "SORT" keyword
            # E.g., "FOR ta1 IN ... SORT ta1.name ASC|DESC ... RETURN {}"
            if order_by:
                ordering = []
                for _, (o_sql, o_params, _) in order_by:
                    ordering.append(o_sql)
                    params.extend(o_params)
                result.append('SORT %s' % ', '.join(ordering))

            # AQL grouping is not yet implemented.
            grouping = []
            for g_sql, g_params in group_by:
                grouping.append(g_sql)
                params.extend(g_params)

            if grouping:
                if distinct_fields:
                    raise NotImplementedError(
                        "annotate() + distinct(fields) is not implemented.")
                if not order_by:
                    order_by = self.connection.ops.force_no_ordering()
                result.append('COLLECT %s' % ', '.join(grouping))

            # In AQL, the "HAVING" clause is replaced by FILTER.
            if having:
                raise NotImplementedError("HAVING SQL clause not implemented.")

            if with_limits:
                if self.query.high_mark is not None:
                    result.append('LIMIT %d' % (self.query.high_mark - self.query.low_mark))
                if self.query.low_mark:
                    if self.query.high_mark is None:
                        val = self.connection.ops.no_limit_value()
                        if val:
                            result.append('LIMIT %d' % val)
                    result.append('OFFSET %d' % self.query.low_mark)

            # RETURN is the last item of the query, other than the list
            # of specific columns to be returned.
            result.append('RETURN')

            # out_cols is the dictionary of "output" columns in the query, e.g.:
            #    RETURN { id : ta1.id, label : ta1.app_label }
            out_cols = {}
            col_idx = 1

            # Loop through the select to get the output columns.
            # The alias will be used to name the JSON element in the AQL RETURN {...}
            # See note about AQL loop vars and aliases at the top of this file.
            for _, (s_sql, s_params), alias in self.select + extra_select:
                if alias:
                    # Rename the output field name to the alias
                    if alias == '__count':  # AQL does not allow the '__' prefix
                        field_name = 'count'
                    else:
                        field_name = '%s' % (self.connection.ops.quote_name(alias))
                elif with_col_aliases:
                    field_name = '%s' % ('Col%d' % col_idx)
                    col_idx += 1
                elif '.' in s_sql:
                    # e.g., s_sql has: 'ta0.id', or 'ta1.app_label'
                    field_name = s_sql.split('.')[1]
                else:
                    logger.debug(f"Unexpected field format: s_sql={s_sql}")
                    field_name = s_sql

                # In the special case of 'id' field (or other PK), we have to use
                # the _key field from the ADB backend.
                if field_name == '_key':
                    field_name = 'id'

                if s_sql.startswith('COUNT'):
                    result.insert(result.index('RETURN'),
                                  f'COLLECT WITH COUNT INTO {field_name}')
                    out_cols[field_name] = field_name
                    params.extend(s_params)
                else:
                    out_cols[field_name] = s_sql
                    params.extend(s_params)

            # Transform the output dict into an AQL return object.
            out_cols = str(out_cols).replace("'", "")
            result.append(out_cols)
            params.extend(f_params)

            for_update_part = None
            if self.query.select_for_update and self.connection.features.has_select_for_update:
                if self.connection.get_autocommit():
                    raise TransactionManagementError(
                            "select_for_update cannot be used outside of a transaction.")

                nowait = self.query.select_for_update_nowait
                skip_locked = self.query.select_for_update_skip_locked
                # If it's a NOWAIT/SKIP LOCKED query but the backend doesn't
                # support it, raise a DatabaseError to prevent a possible
                # deadlock.
                if nowait and not self.connection.features.has_select_for_update_nowait:
                    raise DatabaseError('NOWAIT not supported on this backend.')
                elif skip_locked and not self.connection.features.has_select_for_update_skip_locked:
                    raise DatabaseError('SKIP LOCKED not supported on this backend.')

                for_update_part = self.connection.ops.for_update_sql(
                                    nowait=nowait, skip_locked=skip_locked)

            if for_update_part and self.connection.features.for_update_after_from:
                result.append(for_update_part)

            if for_update_part and not self.connection.features.for_update_after_from:
                result.append(for_update_part)

            result = ' '.join(result), tuple(params)
            return result

        finally:
            # Finally do cleanup - get rid of the joins we created above.
            self.query.reset_refcounts(refcounts_before)

    def test_sql(self, sql):
        # Utility for testing raw AQL
        logger.debug(f"ADB: SQLCompiler().test_sql() : sql={sql}")
        self.connection.ensure_connection()
        result = self.connection.cursor().execute(sql=sql).batch()
        return result

    def execute_sql(self, result_type = MULTI, chunked_fetch = False,
            chunk_size = GET_ITERATOR_CHUNK_SIZE):
        """
        Run the query against the database and returns the result(s). The
        return value is a single data item if result_type is SINGLE, or an
        iterator over the results if the result_type is MULTI.

        result_type is either MULTI (use fetchmany() to retrieve all rows),
        SINGLE (only retrieve a single row), or None. In this last case, the
        cursor is returned if any query is executed, since it's used by
        subclasses such as InsertQuery). It's possible, however, that no query
        is needed, as the filters describe an empty set. In that case, None is
        returned, to avoid any unnecessary database interaction.

        ----
        # https://docs.arangodb.com/3.0/AQL/Fundamentals/BindParameters.html#bind-parameters
        ----

        """

        if not result_type:
            result_type = NO_RESULTS
        try:
            sql, params = self.as_sql()
            if not sql:
                raise EmptyResultSet
        except EmptyResultSet:
            if result_type == MULTI:
                return iter([])
            else:
                return

        self.connection.ensure_connection()
        self.connection.adbcursor().execute(sql)

        if result_type == CURSOR:
            if self.aql_query_context == AQLQueryContext.AQL_QUERY_UPDATE:
                return self.connection.adbcursor().rowcount

            if self.aql_query_context == AQLQueryContext.AQL_QUERY_DELETE:
                return self.connection.adbcursor()

            return self.connection.adbcursor()

        if result_type == SINGLE:
            # Django db models expect:
            #   If no data return False
            #   If there is data, return a single row.
            try:
                val = self.connection.adbcursor().fetchone()
                if val:
                    return val[0:self.col_count]
                return val
            finally:
                self.connection.adbcursor().close()

        if result_type == NO_RESULTS:
            self.connection.adbcursor().close()
            return

        result = self.connection.adbcursor().batch()

        # TTG the below code will never be executed, I think.
        if not self.connection.features.can_use_chunked_reads:
            try:
                # If we are using non-chunked reads, we return the same data
                # structure as normally, but ensure it is all read into memory
                # before going any further.
                return list(result)
            finally:
                # done with the cursor
                self.connection.adbcursor().close()

        return result

    def _make_result(self, entity, fields):
        """
        Decodes values for the given fields from the database entity.

        The entity is assumed to be a dict using field database column
        names as keys. Decodes values using `value_from_db` as well as
        the standard `convert_values`.
        """
        result = []
        for field in fields:
            value = entity.get(field.target.column, None)
            result.append(value)
        return result

    def results_iter(self, results = None, tuple_expected = False,
                    chunked_fetch = False, chunk_size = GET_ITERATOR_CHUNK_SIZE):
        # Results are dictionaries and we can't trust the order of the fields.
        # This part deal with that.
        if results is None:
            results = self.execute_sql(MULTI, chunked_fetch=chunked_fetch, chunk_size=chunk_size)

        fields = [s[0] for s in self.select[0:self.col_count]]

        # Added this part to original ...
        new_result = []
        for item in results:
            new_result.append(self._make_result(item, fields))

        # Now we return to the default django execution.
        converters = self.get_converters(fields)
        for row in new_result:
            if converters:
                row = self.apply_converters(row, converters)

            # yield must be tuple(row) if tuple_expected
            if tuple_expected:
                yield tuple(row)
            else:
                yield (row)


################################################################################
#
# SQLInsertCompiler() provides .as_sql() to convert an Insert query object to
# SQL (AQL in this case), and then .execute_sql() invokes python-arango driver.
#
################################################################################
class SQLInsertCompiler(SQLCompiler, compiler.SQLInsertCompiler):

    aql_query_context = AQLQueryContext.AQL_QUERY_INSERT

    def execute_sql(self, return_id=True):
        # Implemented in order to use the universal execute SQL.
        ids = super().execute_sql(MULTI)
        if len(ids) == 1:
            return ids[0]
        else:
            return ids

    def as_sql(self):
        """Arango INSERT has the following format:

            FOR item IN [{"nome":"B"}, {"nome":"C"}]
                INSERT item IN Usuario
                RETURN NEW._key

        It's naturally bulk.
        """

        opts            = self.query.get_meta()
        collection_name = opts.db_table

        result     = ['FOR', self.get_aql_loop_alias(), 'IN']
        has_fields = bool(self.query.fields)
        fields     = self.query.fields if has_fields else [opts.pk]
        documents  = []

        if has_fields:
            # Prepare the dictionary for insertion.
            for obj in self.query.objs:
                document = {}
                # Walk through each field.
                for f in fields:
                    # Check if the field is an FK.  If so it must be stored as string, not int.
                    if f.is_relation and f.related_model is not None:
                        document[f.column] = str(self.prepare_value(f, self.pre_save_val(f, obj)))
                        logger.debug("{}({}) is a Key to another field ({})".
                            format(f.column, document[f.column], f.description))
                    else:
                        document[f.column] = self.prepare_value(f, self.pre_save_val(f, obj))
                documents.append(document)
        else:
            # An empty object.
            documents.append('{}')

        # Complete the query statement.
        result.append(json.dumps(documents))
        result.extend(('INSERT',
                        self.get_aql_loop_alias(),
                        'IN', collection_name,
                        'RETURN NEW._key'))

        # return the result and an empty tuple.
        result = " ".join(result)
        return result, ()


class SQLUpdateCompiler(SQLCompiler):
    aql_query_context = AQLQueryContext.AQL_QUERY_UPDATE

    def as_sql(self):
        """
        Create SQL for this query; return SQL string and list of parameters.
        Need to return the fully formed AQL and parameters tuple.

        Arango UPDATE has several available syntaxes:
            UPDATE <key> WITH <doc> IN <collection> <options>  # update "row" in "table"
            UPDATE            <doc> IN <collection> <options>  # alter table
            FOR <alias> IN <table> FILTER <field> == <val> UPDATE WITH { <key:val>, } IN <table>

            # Example of update to one row in the table:
            > UPDATE { _key: '343500' } with { title: 'AD for new car' } IN testdb_ad

            # Example of altering the collection (adding a new column):
            > FOR ad in testdb_ad UPDATE ad WITH { shares: 0 } in testdb_ad

            # Approach used below:
            FOR ta0 IN testdb_ad                # AQL "SELECT"
                FILTER ta0._key == '650565'     # AQL "WHERE" clause
                    UPDATE ta0 WITH { title : 'FK test1', description : 'Ad test1', views : 0 }
                        IN testdb_ad 
        """

        self.pre_sql_setup()
        if not self.query.values:
            return '', ()

        qn = self.quote_name_unless_alias
        values, update_params = [], []
        for field, model, val in self.query.values:
            if hasattr(val, 'resolve_expression'):
                val = val.resolve_expression(self.query, allow_joins=False, for_save=True)
                if val.contains_aggregate:
                    raise FieldError("Aggregate functions are not allowed in this query")
                if val.contains_over_clause:
                    raise FieldError('Window expressions are not allowed in this query.')
            elif hasattr(val, 'prepare_database_save'):
                if field.remote_field:
                    val = field.get_db_prep_save(val.prepare_database_save(field),
                                                 connection=self.connection)
                else:
                    raise TypeError(
                        "Tried to update field %s with a model instance, %r. "
                        "Use a value compatible with %s."
                        % (field, val, field.__class__.__name__))
            else:
                val = field.get_db_prep_save(val, connection=self.connection)

            # get_db_prep_save converts FK fields from string back to int.
            if field.is_relation and field.related_model is not None:
                val = str(val)

            if hasattr(field, 'get_placeholder'):
                placeholder = field.get_placeholder(val, self, self.connection)
            else:
                placeholder = '%s'
            name = field.column
            if hasattr(val, 'as_sql'):
                sql, params = self.compile(val)
                values.append('%s = %s' % (qn(name), placeholder % sql))
                update_params.extend(params)
            elif val is not None:
                #values.append('%s = %s' % (qn(name), placeholder))
                if field.get_internal_type() == 'IntegerField':
                    values.append('%s : %s' % (qn(name), val))
                else:
                    values.append('%s : \'%s\'' % (qn(name), val))
                update_params.append(val)
            else:
                values.append('%s : null' % qn(name))

        table = self.query.base_table
        loop_alias = self.get_aql_loop_alias(table)
        where, params = self.compile(self.query.where)
        result = ['FOR', loop_alias, 'IN', table, ]
        if where:
            result.append('FILTER')
            result.append(where % tuple(params))

        qstr = ''
        for val in values:
            qstr += f"{val}, "
        result.append('UPDATE %s WITH { %s } IN %s' % (loop_alias, qstr[:-2], table))
        sql = ' '.join(result), (params + update_params)
        logger.debug(f"ADB: SQLUpdateCompiler.as_sql() sql={sql}")
        return ' '.join(result), (params + update_params)


class SQLDeleteCompiler(SQLCompiler):
    aql_query_context = AQLQueryContext.AQL_QUERY_DELETE

    def as_sql(self):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.

        # Multiple
        FOR user IN users
            FILTER user.active == 1
            REMOVE user IN users

        # Single
        REMOVE { _key:"1" }
            IN users

        """

        for tables in self.query.table_map.values():
            assert len([t for t in tables if self.query.alias_refcount[t] > 0]) == 1, \
            "Can only delete from one table at a time."

        table = tables[0]
        loop_alias = self.get_aql_loop_alias(table)

        result = ['FOR', loop_alias, 'IN', table, ]

        where, w_params = self.compile(self.query.where)
        if where:
            result.append('FILTER')
            result.append(where % tuple(w_params))

        result.extend(('REMOVE', loop_alias, 'IN', table))
        result.extend(('RETURN', 'OLD._key'))

        logger.debug(f"ADB: SQLDeleteCompiler.as_sql() sql={result}")

        return ' '.join(result), tuple(w_params)

# compiler.py
