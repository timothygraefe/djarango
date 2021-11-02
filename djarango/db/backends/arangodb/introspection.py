#
# instrospection.py
#
# Timothy Graefe, Javamata LLC
#

import logging

from django.db.backends.dummy.base import complain, ignore
from django.db.backends.base.introspection import BaseDatabaseIntrospection, TableInfo
from typing import List

logger = logging.getLogger('django.db.backends.arangodb')

class DatabaseIntrospection(BaseDatabaseIntrospection):

    def get_collections(self):
        return self.connection.Database.adb.collections()

    def get_table_list(self, cursor)->List[TableInfo]:
        """Get the collections dict and return it as list of TableInfos"""
        collections = self.connection.Database.adb.collections()

        # TableInfo namedtuple includes the table name and table type.
        # Typically this means is the table a "table" or "view".
        # In ArangoDB table type is either a document or projection.
        table_list = [  TableInfo(table['name'],
                                  { 'document': 't', 'projection': 'v'}.get(table['type']) )
                            for table in collections ]

        return table_list

    def get_table_description(self, cursor, table_name):
        # Do not remove 'cursor' from the signature.

        # Get the entire list, since ArangoDB driver grabs the full list anyway.
        collections = self.connection.Database.adb.collections()

        # The list comprehension below will return a list of indices that match
        # the given table name.  In this case, there should be just one.
        idx = [ x for x in range(len(collections)) if collections[x]['name'] == table_name ]
        if len(idx) == 0:
            return None

        return collections[idx[0]]

    def print_header(self):
        print("\n  {:>8} : {:30} : {:5} : {:8} : {:8} : {:8}".
            format("Table ID", "Table Name", "  Sys", "Type", "Status", " Records"))

    def print_table(self, t):
        print("  {:>8} : {:30} : {:5} : {:8} : {:8} : {:8}".
            format(t['id'], t['name'], t['system'], t['type'], t['status'], t['count']))

    def dump_tables(self):
        # Get the entire list, since ArangoDB driver grabs the full list anyway.
        collections = self.connection.Database.adb.collections()
        print("dump_tables {type(collections)}")
        self.print_header()

        for t in sorted(collections, key = lambda x: x['name']):
            coll = self.connection.Database.adb[t['name']]
            t['count'] = coll.count()
            self.print_table(t)

    def get_nonsystem_tables(self, verbose = False):
        collections = self.connection.Database.adb.collections()
        tl = [ table for table in collections if table['system'] == 0 ]
        if verbose:
            self.print_header()
            for t in sorted(tl, key = lambda x: x['name']):
                coll = self.connection.Database.adb[t['name']]
                t['count'] = coll.count()
                self.print_table(t)
        return tl

    def get_adbsystem_tables(self, verbose = False):
        collections = self.connection.Database.adb.collections()
        tl = [ table for table in collections if table['system'] == 1 ]
        if verbose:
            self.print_header()
            for t in sorted(tl, key = lambda x: x['name']):
                coll = self.connection.Database.adb[t['name']]
                t['count'] = coll.count()
                self.print_table(t)
        return tl

    def get_nonsystem_indexes(self, verbose = False):
        collections = self.connection.Database.adb.collections()
        tl = [ table for table in collections if table['system'] == 0 ]
        if verbose:
            self.print_header()
            for t in sorted(tl, key = lambda x: x['name']):
                coll = self.connection.Database.adb[t['name']]
                indexes = coll.indexes()
                print(f"Collection: {t['name']}")
                print(f"  indexes: {indexes}")
        return tl

    def get_adbsystem_indexes(self, verbose = False):
        collections = self.connection.Database.adb.collections()
        tl = [ table for table in collections if table['system'] == 1 ]
        if verbose:
            self.print_header()
            for t in sorted(tl, key = lambda x: x['name']):
                coll = self.connection.Database.adb[t['name']]
                indexes = coll.indexes()
                print(f"Collection: {t['name']}")
                print(f"  indexes: {indexes}")
        return tl

    def get_collection_docs(self, name, verbose = False):
        return self.connection.Database.get_collection_docs(name)

    # copied from dummy/base.py - open items that need to be implemented
    get_relations   = complain
    get_indexes     = complain
    get_key_columns = complain

    def get_constraints(self, cursor, table_name):
        """
        Retrieve any constraints or keys (unique, pk, fk, check, index)
        across one or more columns.

        Return a dict mapping constraint names to their attributes,
        where attributes is a dict with keys:
         * columns: List of columns this covers
         * primary_key: True if primary key, False otherwise
         * unique: True if this is a unique constraint, False otherwise
         * foreign_key: (table, column) of target, or None
         * check: True if check constraint, False otherwise
         * index: True if index, False otherwise.
         * orders: The order (ASC/DESC) defined for the columns of indexes
         * type: The type of the index (btree, hash, etc.)

        Some backends may return special constraint names that don't exist
        if they don't name constraints of a certain type (e.g. SQLite)
        """
        logger.debug(f"get_constraints: {table_name}")

        constraints = {}

        # Fetch the schema for the table.  But, since ArangoDB is schema-less,
        # and does not have tables, we will fetch the referenced collection.
        table_schema = self.get_table_description(cursor, table_name)

        # Need to indicate if any col is PK, FK, unique, check, or index.
        # _id is the PK for all tables.
        # There will need to be a schema description to indicate which are FK.
        # ADB is schema-less, but allows specification of a schema (v3.7+).
        # The ADB python driver supports the schema capability.  That should be
        # added here in a future version.  For now, constraints are not applied.
        # Sample code below, for reference.

        schema = {
            'rule' : {
                'properties': {
                    'street_num' :  { 'type' : 'number' },
                    'street_name' : { 'type' : 'string' },
                    'street_type' : { 'enum' : [ 'street', 'avenue', 'boulevard' ] },
                    'occupant_names' : {
                        'type'  : 'array',
                        'items' : { 'type': 'string', 'maximum': 20 } }
                    }, 
                # don't allow extra fields in the document
                # 'additionalProperties' : False,

                # any extra fields in the document must be a string
                'additionalProperties': { 'type': 'string' },

                # non-null fields in the document
                'required': [ 'street_num', 'street_name', ]
            }, # describes the record shape
            'level' : 'moderate',                   # level of schema validation applied by ADB
                                                    # Validation will impact DB performance;
                                                    # it may be best to set to "none", and only
                                                    # explicitly invoke schema validation when
                                                    # appropriate.
            'message' : 'Schema validation failed', # error message if validation fails
        }

        constraints['__dummy__'] = {
            'columns': ['name', 'applied'],
            'primary_key': True,
            'unique': False,
            'foreign_key': None,
            'check': False,
            'index': False,
        }

        return constraints

    # Utility
    def delete_all_collections(self, verbose = False):
        collections = self.connection.Database.adb.collections()
        tl = [ table for table in collections if table['system'] == 0 ]
        for t in tl:
            logger.debug(f"deleting non-system table: {t['name']}")
            self.connection.Database.adb.delete_collection(t['name'])

# instrospection.py
