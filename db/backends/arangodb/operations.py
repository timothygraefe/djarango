#
# operations.py
#

# Python imports
import datetime
from typing import Iterable

# Django imports
from django.conf import settings
from django.db.backends.base.operations import BaseDatabaseOperations

class DatabaseOperations(BaseDatabaseOperations):
    compiler_module = "django.db.backends.arangodb.compiler"

    def distinct_sql(self, fields: Iterable[str]) -> str:
        """Returns an SQL DISTINCT clause which removes duplicate rows from the
        result set. If any fields are given, only the given fields are being
        checked for duplicates.
        """
        # TODO: Implement this for arangoDB
        if fields:
            raise NotImplementedError('DISTINCT ON fields not currently supported')
        else:
            return 'DISTINCT'

    def get_db_converters(self, expression):
        """
        Get a list of functions needed to convert field data.

        Some field types on some backends do not provide data in the correct
        format, this is the hook for converter functions.
        """
        # TODO: Implement this for arangoDB
        return []

    def max_name_length(self) -> int:
        """Max length of collection name."""
        return 254

    def pk_default_value(self):
        """
        Returns None, to be interpreted by back-ends as a request to
        generate a new key for an "inserted" object.
        """
        return None

    def quote_name(self, name):
        """Does not do any quoting, as it is not needed for ArangoDB."""
        return name

    def prep_for_like_query(self, value):
        """Does no conversion, parent string-cast is SQL specific."""
        return value

    def year_lookup_bounds_for_date_field(self, value):
        """
        Converts year bounds to date bounds as these can likely be
        used directly, also adds one to the upper bound as it should be
        natural to use one strict inequality for BETWEEN-like filters
        for most nonrel back-ends.
        """
        first = datetime.date(value, 1, 1)
        second = datetime.date(value + 1, 1, 1)
        return [first, second]

# end operations.py
