from django.db.backends.base.features import BaseDatabaseFeatures

class DatabaseFeatures(BaseDatabaseFeatures):
    can_return_id_from_insert       = True
    can_use_chunked_reads           = True
    has_bulk_insert                 = True
    can_return_ids_from_bulk_insert = False
    supports_timezones              = False

