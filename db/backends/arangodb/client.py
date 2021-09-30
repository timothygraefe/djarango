# client.py
#
# Timothy Graefe, Javamata LLC
#

import logging

# Django imports
from django.conf                    import settings
from django.db.utils                import DatabaseError
from django.db.backends.base.client import BaseDatabaseClient
from django.core.exceptions         import ImproperlyConfigured

# Arango Python driver (python-arango) imports.
from arango                         import ArangoClient

debug_client = True

logger = logging.getLogger('django.db.backends.arangodb')

class Database(object):
    # Make this class a singleton.
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = super(Database, cls).__new__(cls)
        return cls.instance

    # aclient gets instantiated to an ArangoClient instance.
    # ArangoClient is the python driver used to invoke the ArangoDB REST API.
    aclient     = None

    # adb is an ArangoClient.db() instance.
    # It represents a specific database to which the ArangoClient has connected.
    adb         = None

    conn_params = {}

    # List of valid configuration keywords; used for validating settings.
    client_cfgs = [ 'ENGINE', 'HOST', 'PORT', 'HOSTS' ]
    client_opts = [ 'HOST_RESOLVER', 'HTTP_CLIENT', 'SERIALIZER', 'DESERIALIZER' ]
    conn_cfgs   = [ 'NAME', 'USER', 'PASSWORD' ]
    conn_opts   = [ 'ATOMIC_REQUESTS', 'AUTOCOMMIT', 'CONN_MAX_AGE', 'OPTIONS',
                    'TIME_ZONE', 'USE_TZ', 'TEST' ] 

    def get_connection_params(self, settings):
        # Get parameters for Arango client instance and associated db.
        # Only do this once - i.e., it should be a singleton.
        if self.ready():
            return self.conn_params

        # Check that parameters in settings are valid.
        errs = {}
        for setting, val in settings.items():
            if (not ((setting in self.client_cfgs) or
                     (setting in self.client_opts) or
                     (setting in self.conn_cfgs)   or
                     (setting in self.conn_opts))):
                errs[setting] = val

        if len(errs) > 0:
            raise ImproperlyConfigured(
                "settings.DATABASES has unrecognized settings: {}".format(errs))

        # Sample parameters are given below for ArangoClient.
        """
            aclient = ArangoClient(
                hosts = 'http://127.0.0.1:8529' | [ list of hosts in cluster ],
                host_resolver = 'roundrobin' | 'random',
                http_client = user-supplied HTTP client if desired,
                serializer = user-supplied callable to serialize JSON if desired,
                deserializer = user-supplied callable to deserialize JSON if desired)
        """

        # Parse the client configuration first.
        # python-arango supports a single host, or list of hosts (cluster).
        host  = settings.get('HOST')
        hosts = settings.get('HOSTS')
        port  = settings.get('PORT', '8529')

        if (host == ''):
            host = None

        if hosts == None:
            if host == None:
                raise ImproperlyConfigured("Neither 'HOST' nor 'HOSTS' configured")
            hosts = [ host ]
        elif host != None:
            raise ImproperlyConfigured(
                "Both 'HOST' : '{}' and 'HOSTS' : {} configured".format(host, hosts))

        # The connection from ArangoClient is to an HTTP endpoint, not just ip:port

        # Create a properly formated list of hosts.  There will be multiple
        # hosts (multiple HTTP endpoints) in an ArangoDB cluster.
        adbhosts = []
        for host in hosts:
            adbhosts.append('http://' + host + ':' + port)

        # Build a list of keyword options that will be used in client instantiation.
        adb_kwopts = {}
        for cfg in self.client_opts:
            adb_kwopts[ cfg.lower() ] = settings.get(cfg, None)

        #
        # The '**' operator is used here to avoid multiple if/else statements,
        # each to invoke different function signatures.  We want to avoid
        # passing "None" to the ArangoClient; the client should use defaults.
        # Stackoverflow has a good explanation of avoiding passing arguments if
        # they are "None":
        #      https://stackoverflow.com/questions/52494128/
        #          call-function-without-optional-arguments-if-they-are-none
        #

        self.aclient = ArangoClient(adbhosts,
                                    **{k: v for k, v in adb_kwopts.items() if v is not None })
        if self.aclient == None:
            raise DatabaseError("ArangoClient instantiation failed")

        # The client instantiation has succeeded, now get parameters for the db.
        # The db object internally maintains a connection.
        for cfg in self.conn_cfgs:
            if cfg == 'USER':
                self.conn_params[ 'username' ] = settings.get(cfg, None)
            else:
                self.conn_params[ cfg.lower() ] = settings.get(cfg, None)

        # Return the connection parameters to the caller.
        return self.conn_params

    def connect(self, **cp):
        # Should be called with the previously parsed and validated conn_params.
        if self.ready():
            return self.adb

        # A call to the "db()" method of the client is used to establish the connections.
        # Only name, username, and password are provided in the config.
        """
            aclient.db(
                self,
                name: str = "javamatadb",
                username: str = "root",
                password: str = "",
                verify: bool = False,
                auth_method: str = "basic",
                superuser_token: Optional[str] = None)
        """

        if debug_client:
            cp['verify'] = True

        self.adb = self.aclient.db(**{k: v for k, v in cp.items() if v is not None })

        # ArangoClient.db() returns a StandardDatabase object.
        if self.adb == None:
            raise DatabaseError("ArangoClient instantiation failed")

        return self.adb

    def ready(self) -> bool:
        return (self.aclient and self.adb and (len(self.conn_params) > 0))

    def verify(self) -> bool:
        if not self.ready():
            raise DatabaseError("ArangoClient Database not ready")

        try:
            self.adb._conn.ping()
        except ServerConnectionError as err:
            raise err
        except Exception as err:
            raise ServerConnectionError(f"bad connection: {err}")

        return True

    def close(self):
        if not self.ready():
            return

        self.aclient.close()

    def create_collection(self, name):
        if not self.ready():
            logger.debug("ArangoClient: create_collection() no connection to DB")
            return

        self.adb.create_collection(name)

    def delete_collection(self, name):
        if not self.ready():
            logger.debug("ArangoClient: delete_collection() no connection to DB")
            return

        self.adb.delete_collection(name)

    def delete_document(self, collection, key):
        if not self.ready():
            logger.debug("ArangoClient: delete_document() no connection to DB")
            return

        coll = self.adb[collection]
        coll.delete(key)

    def get_document(self, collection, key):
        if not self.ready():
            logger.debug("ArangoClient: get_document() no connection to DB")
            return

        coll = self.adb[collection]
        return coll.get({ '_key': str(key) })

class DatabaseClient(BaseDatabaseClient):
    # Use arangosh as the DB client shell.
    executable_name = 'arangosh'

    @classmethod
    def runshell_db(cls, conn_params):
        # Client invocation:
        # arangosh --server.database <dbname> --server.endpoint tcp://<host>:<port> \
        #           --server.username <username> --server.password <password>
        args = [cls.executable_name]

        host = conn_params.get('host', '')
        port = conn_params.get('port', '')
        dbname = conn_params.get('database', '')
        user = conn_params.get('user', '')
        passwd = conn_params.get('password', '')

        if not host:
            host = 'localhost'
        if not port:
            port = '8529'

        endpoint = r'tcp://{}:{}'.format(host, port)
        args += ['--server.endpoint', endpoint ]

        if dbname:
            args += ['--server.database', dbname]
        if user:
            args += ['--server.username', user]
        if passwd:
            args += ['--server.password', passwd]

    def runshell(self):
        DatabaseClient.runshell_db(self.adb.get_connection_params())


