#
# edges.py
#
# Timothy Graefe    Javamata LLC
#

import functools
import inspect
from functools import partial

from django.core import checks, exceptions
from django.db.models.utils import make_model_tuple
from django.db.models.fields.related import RelatedField, ForeignObjectRel
from django.db.models.fields.related import resolve_relation, lazy_related_operation
from django.utils.translation import gettext_lazy as _
from django.db.migrations.operations.special import RunSQL

from .edge_descriptors import EdgeDescriptor, ReverseEdgeDescriptor

# create_graph_collections is adapted from create_many_to_many_intermediary_model
# in the ManyToManyField class.  In the m2m case, a 'through' table must
# be created with key pairs (one for each side of an m2m relationship).
# This does not carry over directly to the edge field case, but could be used to
# trigger the creation of the graph that contains the edge definition (which in
# turn contains the source and target model vertices).
#
# 10/11/2021
# After more thought - this should not be used at all.
# The purpose here is to create a Django model, which will go into a migration file,
# and then the model in the migration file will be used to create the table.
# I do not want to create a new model for the graph object, since it does not
# correspond to a DB table.  It would require definition within Django of the new
# object, which gets exported to the migrations file, which finally generates the
# graph during migration.  It will be much easier to only export the edge field
# in the migration file, and during the migration process, create or update the
# graph as needed.  I don't think it is necessary to provide direct access in
# Django to the edge definitions.

# The only value here is the code that sets up the remote_field attributes.
# The Django edge field, should have a remote field that provides accessors to the
# graph object:
#       mymodel.myedge.target() - vertex on other end of the edge
#       mymodel.myedge.source() - vertex on this end of the edge (i.e., mymodel instance)
#       mymodel.myedge.graph()  - top level of graph containing the edge
#
# some remote_field attributes:
#   remote_field                            - this gets set to <EdgeRel: testdb.modela>
#   remote_field.model                      - set to 'ModelB' (string then class)
#   remote_field.model._meta                - ModelB options
#   remote_field.model._meta.swapped
#   remote_field.model._meta.verbose_name
#
#   I think the remote field model should be the target vertex model (i.e., ModelB
#   in my example code).
#
#   remote_field.related_name
#   remote_field.related_query_name
#   remote_field.field_name
#
#   remote_field.limit_choices_to
#   remote_field.on_delete
#   remote_field.db_constraint
#   remote_field.parent_link
#
#   remote_field.through    -- 'through' should not exist for EdgeField
#   remote_field.through._meta
#   remote_field.through._meta.auto_created
#   remote_field.through._meta.app_label
#   remote_field.through._meta.object_name
#   remote_field.through._meta.fields
#   remote_field.through._meta.db_table
#   remote_field.through._meta.fields
#   remote_field.through.through_fields[]
#
#   remote_field.symmetrical
#
#   remote_field.is_hidden() - just checks for "+"
#   remote_field.get_accessor_name()
#   remote_field.set_field_name()
#


class EdgeRel(ForeignObjectRel):
    """
    Used by EdgeField to store information about the edge relation.

    ``_meta.get_fields()`` returns this class to provide access to the field
    flags for the reverse relation.
    """

    def __init__(self, field, to, graph_name=None, edge_name=None):
        # super().__init__() resolves to ForeignObjectRel constructor.
        # Nothing significant, other than setting field and model attributes.
        super().__init__(field, to)

        if edge_name is not None:
            self.edge_name = edge_name

        if graph_name is not None:
            self.graph_name = graph_name

        self.through        = None
        self.through_fields = None
        self.symmetrical    = False
        self.db_constraint  = None

    def get_related_field(self):
        """
        Return the field in the 'to' object to which this relationship is tied.
        Provided for symmetry with ManyToOneRel.
        """
        opts = self.through._meta
        if self.through_fields:
            field = opts.get_field(self.through_fields[0])
        else:
            for field in opts.fields:
                rel = getattr(field, 'remote_field', None)
                if rel and rel.model == self.model:
                    break
        return field.foreign_related_fields[0]

#
# Main implementation of links from Django to ArangoDB graph DB.
#
#   EdgeField
#   Example usage in a model:
#   class MyModel(models.Model):
#       ...
#       edge_to_b   = EdgeField('ModelB', edge_name='edge_ab', graph_name='graph_ab')
#
#
class EdgeField(RelatedField):
    """
    Provide a graph edge relation.  The end result will be a 'field'
    in the list of fields in the migration file.

    The edge field does not correspond to a column in a DB (similar to the m2m
    field model).  Instead, it is a hook to use for graph queries.

      > When 'makemigrations' runs, I want to see this in the relevant model
        migrations:
        migrations.CreateModel(
        name='ModelA',
        fields=[ (...),
            # field name                target model          graph name      edge name
            ('edge_b', models.EdgeField('ModelB', graph_name='SomeGraphName', edge_name='ab')),

        # the graph_name and edge_name are optional.

      > When migrations run, create graph in ADB with an edge definition:
          ModelA is source vertex collection
          ModelB is target vertex collection
          SomeGraphName is the graph containing the edge definition
          ab is the name of the edge definition (optional; automatically generated otherwise)
    """

    # Field flags - TTG not relevant for EdgeField

    # The edge descriptor concept is worth reusing.
    # The name of the edge field should be used to access the graph:
    #   mymodel.edge_b.source.someGraphQuery()
    #   mymodel.edge_b.target.someGraphQuery()
    #   mymodel.edge_b.graph.someGraphQuery()
    related_accessor_class         = ReverseEdgeDescriptor
    forward_related_accessor_class = EdgeDescriptor
    rel_class                      = EdgeRel

    description = _("ArangoDB Edge field definition")

    # 'to' is the model on the other end of the edge.
    # 'graph_name' is a name given to the graph containing the edge definition
    # 'through' should not be used
    # 'related_name' is the name of an accessor that will be added to the 'to'
    #       model to provide access to attributes that are part of that model
    #       It should not be used - the accessor names will be auto-generated.
    #       Perhaps added in a future release.

    def __init__(self, to, graph_name=None, edge_name=None,
                 swappable=True, **kwargs):
        # During __init__, 'to' must be a class or a string.  If it is a string,
        # the 'try' block below will fail with 'AttributeError'.  This is fine
        # as long as the parameter is a string.
        try:
            to._meta
        except AttributeError:
            assert isinstance(to, str), (
                "%s(%r) is invalid. First parameter to EdgeField must be "
                "either a model, a model name" %
                (self.__class__.__name__, to)
            )

        # Invoke the constructor for EdgeRel
        kwargs['rel'] = self.rel_class(
            self, to, graph_name=graph_name, edge_name=edge_name)

        # super().__init__() resolves to Field() constructor, found in:
        #       django.db.models.fields.__init__.py
        # It sets the remote_field attribute to the rel_class - i.e., EdgeRel
        #   Looks like it is not working at the moment ...
        #   Note that within super().__init__() we have:
        #       self.__class__          # EdgeField
        #       self.__class__.__mro__  # class heirarchy (documented below):

        """
            (<class 'django.db.backends.arangodb.fields.edges.EdgeField'>,
             <class 'django.db.models.fields.related.RelatedField'>,
             <class 'django.db.models.fields.mixins.FieldCacheMixin'>,
             <class 'django.db.models.fields.Field'>,
             <class 'django.db.models.query_utils.RegisterLookupMixin'>,
             <class 'object'>)
        """

        super().__init__(**kwargs)
        self.swappable = swappable

        # After this, execution returns to the ModelBase.__new__ method.
        # Note that the attrs includes a list of the fields, including EdgeField.

        # EdgeField is added to the list of contributable_attrs, along with other
        # DB fields (which is correct).
        # ModelBase then creates a new super_new for the model class containing
        # EdgeField, based on the characteristics of ModelA, and subsequently adds
        # the contributable_attrs to the class (including EdgeField).
        # It invokes contribute_to_class in this file when adding EdgeField.

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_unique(**kwargs),
#           *self._check_relationship_model(**kwargs),
            *self._check_ignored_options(**kwargs),
#           *self._check_table_uniqueness(**kwargs),
        ]

    def contribute_to_class(self, cls, name, **kwargs):
        # TTG copied from ManyToManyField class.  This is needed or subsequent
        # checks on related models will fail because _meta is not present.

        # To support multiple relations to self, it's useful to have a non-None
        # related name on symmetrical relations for internal reasons. The
        # concept doesn't make a lot of sense externally ("you want me to
        # specify *what* on my non-reversible relation?!"), so we set it up
        # automatically. The funky name reduces the chance of an accidental
        # clash.

        # cls - class to which we should contribute (e.g., <class 'testdb.models.ModelA'>
        # name - name of the class member, e.g., 'modelb'

        # TTG: symmetrical should not be supported for EdgeField
        assert self.remote_field.symmetrical is False, ("Edge models cannot be symmetric")
        assert self.remote_field.is_hidden() is False, ("Edge models cannot hide remote fields")

        srcmodel = cls._meta.object_name.lower()
        dstmodel = name.lower()
        if not hasattr(self.remote_field, 'edge_name'):
            self.remote_field.edge_name = "edge_def_%s_%s" % (srcmodel, dstmodel)

        if not hasattr(self.remote_field, 'graph_name'):
            self.remote_field.graph_name = "graph_%s_%s" % (srcmodel, dstmodel)

        # contribute_to_class() ultimately uses the schema editor to add the
        # EdgeField to the parent class.
        super().contribute_to_class(cls, name, **kwargs)

        # This needs to be done after contribute_to_class, or it is treated as a kwarg.
#       self.remote_field.related_name = "edge_def_%s_%s" % (srcmodel, dstmodel)

        # Parse the source and destination vertex collections.  These names are
        # not allowed to be user-specified.  These will be used in the add_field
        # method of the schema editor.
        src_vc = "%s_%s" % (cls._meta.app_label, srcmodel)
        dst_vc = "%s_%s" % (cls._meta.app_label, dstmodel)

        self.from_vertex_collection = src_vc
        self.to_vertex_collection   = dst_vc

        # Add the descriptor for the edge relation.  It will be used for the accessors.
        # cls example: <class 'testdb.models.ModelA'>
        # self.name is the name of the EdgeField member of cls (e.g., 'modelb')
        # self.remote_field is the EdgeRel object, e.g.: <EdgeRel: testdb.modela>
        setattr(cls, self.name, EdgeDescriptor(self.remote_field, reverse=False))

    def contribute_to_related_class(self, cls, related):
        # Edge models should not contribute to the related class.
        if not self.remote_field.is_hidden() and not related.related_model._meta.swapped:
            setattr(cls._meta.concrete_model,
                    related.get_accessor_name(),
                    self.related_accessor_class(related))
            # While 'limit_choices_to' might be a callable, simply pass
            if self.remote_field.limit_choices_to:
                cls._meta.related_fkey_lookups.append(self.remote_field.limit_choices_to)

    def deconstruct(self):
        # Return a tuple of 4 items:
        #   field's attribute name (handled by base class)
        #   full import path of the field class (handled by base class)
        #   positional arguments (as a list)
        #   keyword arguments (as a dict)
        # It must be possible to pass these arguments into __init__() to
        # reconstruct the object with identical state.
        # Check model migrations to verify this works as expected.
        # Can write unit tests that run deconstruct() --> __init__(), e.g.:
        """
        name, path, args, kwargs = my_field_instance.deconstruct()
        new_instance = MyField(*args, **kwargs)
        self.assertEqual(my_field_instance.some_attribute,
                         new_field_instance.some_attribute)
        """
        name, path, args, kwargs = super().deconstruct()

        # There is only 1 positional arguments: target model (e.g., 'ModelB')
        # There are only 2 keyword arguments: graph_name, edge_name

        # Get arg 1 - think it is passed as kwarg 'to'
        if isinstance(self.remote_field.model, str):
            kwargs['to'] = self.remote_field.model
        else:
            kwargs['to'] = "%s.%s" % (
                self.remote_field.model._meta.app_label,
                self.remote_field.model._meta.object_name,
            )

        # Get keyword arg graph_name:
        if getattr(self.remote_field, 'graph_name', None) is not None:
            if isinstance(self.remote_field.graph_name, str):
                kwargs['graph_name'] = self.remote_field.graph_name
            elif not self.remote_field.graph_name._meta.auto_created:
                kwargs['graph_name'] = "%s.%s" % (
                    self.remote_field.graph_name._meta.app_label,
                    self.remote_field.graph_name._meta.object_name,
                )

        # Get keyword arg edge_name:
        if getattr(self.remote_field, 'edge_name', None) is not None:
            if isinstance(self.remote_field.edge_name, str):
                kwargs['edge_name'] = self.remote_field.edge_name
            elif not self.remote_field.edge_name._meta.auto_created:
                kwargs['edge_name'] = "%s.%s" % (
                    self.remote_field.edge_name._meta.app_label,
                    self.remote_field.edge_name._meta.object_name,
                )

        return name, path, args, kwargs

    def db_check(self, connection):
        # As below.
        return None

    def db_type(self, connection):
        # This indicates the type of the data to be stored in the DB, e.g.:
        # 'datetime' or 'timestamp' - not applicable for NoSQL DB like ArangoDB.
        # Similar to ManyToManyField the edge is not represented by a single
        # column, so return None.
        return None

    def rel_db_type(self, connection):
        # As above.
        return None

    def db_parameters(self, connection):
        return {"type": None, "check": None}

    def _check_unique(self, **kwargs):
        # Don't know what unique means in this case, but it appears it is not being set.
        if self.unique:
            return [checks.Error('EdgeFields cannot be unique.', obj=self, id='fields.E330',)]
        return []

    def _check_ignored_options(self, **kwargs):
        warnings = []
        return warnings

    # Checking on destination and through models here.  Copied from ManyToManyField.
    def _check_relationship_model(self, from_model=None, **kwargs):
        if hasattr(self.remote_field.through, '_meta'):
            qualified_model_name = "%s.%s" % (
                self.remote_field.through._meta.app_label, self.remote_field.through.__name__)
        else:
            qualified_model_name = self.remote_field.through

        errors = []

        if self.remote_field.through not in self.opts.apps.get_models(include_auto_created=True):
            # The relationship model is not installed.
            errors.append(
                checks.Error(
                    "Field specifies an edge relation through model "
                    "'%s', which has not been installed." % qualified_model_name,
                    obj=self,
                    id='fields.E331',
                )
            )

        else:
            assert from_model is not None, (
                "EdgeField with intermediate "
                "tables cannot be checked if you don't pass the model "
                "where the field is attached to."
            )

        # Some useful local variables
        to_model = resolve_relation(from_model, self.remote_field.model)
        from_model_name = from_model._meta.object_name
        if isinstance(to_model, str):
            to_model_name = to_model
        else:
            to_model_name = to_model._meta.object_name
        relationship_model_name = self.remote_field.through._meta.object_name
        self_referential = from_model == to_model

        # Check symmetrical attribute.  "symmetrical" means different things
        # in m2m and edge fields.  In this code, symmetrical means that the
        # same model is on both ends of a relationship.  This is valid for
        # edge fields also.  But, edge fields are defined in this implementation
        # to always be in 1 direction (source to target).  A bidirectional
        # relationship can be created by creating 2 edges, one in each direction.

        return errors

    def _get_edge_db_table(self, opts):
        """
        Function that can be curried to provide the edge table name for this
        relation.
        """
        return None

    def cast_db_type(self, connection):
        return super().cast_db_type(connection)

    def get_internal_type(self):
        return "EdgeField"

    def to_python(self, value):
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self.to_python(value)


# end fields.py
