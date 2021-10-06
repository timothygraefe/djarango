
from django.db.models.fields.related import RelatedField
from django.db.models.fields.reverse_related import ForeignObjectRel
from django.utils.translation import gettext_lazy as _


class EdgeRel(ForeignObjectRel):
    """
    Used by EdgeField to store information about the edge relation.

    ``_meta.get_fields()`` returns this class to provide access to the field
    flags for the reverse relation.
    """

    def __init__(self, field, to, related_name=None, related_query_name=None,
                 limit_choices_to=None, symmetrical=True, through=None,
                 through_fields=None, db_constraint=True):
        super().__init__(
            field, to,
            related_name=related_name,
            related_query_name=related_query_name,
            limit_choices_to=limit_choices_to,
        )

        # This is applicable for M2M field but not edge field.
#       if through and not db_constraint:
#           raise ValueError("Can't supply a through model and db_constraint=False")
        self.through = through

        if through_fields and not through:
            raise ValueError("Cannot specify through_fields without a through model")
        self.through_fields = through_fields

        self.symmetrical = symmetrical
        self.db_constraint = db_constraint

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


class EdgeField(RelatedField):
    """
    Provide a graph edge relation by using an intermediary model that
    provides an edge definition.

    Unless a ``through`` model was provided, EdgeField will use the
    create_edge_intermediary_model factory to automatically generate
    the intermediary edge model.
    """

    # Field flags
    many_to_many = True
    many_to_one = False
    one_to_many = False
    one_to_one = False

    rel_class = EdgeRel
    description = _("ArangoDB Edge field definition")

    # 'to' is the model on the other end of the edge.
    # 'through' is the name of the edge model
    # 'related_name' is the name of an accessor that will be added to the 'to'
    #       model to provide access to attributes that are part of that model

    def __init__(self, to, related_name=None, related_query_name=None,
                 limit_choices_to=None, symmetrical=None, through=None,
                 through_fields=None, db_constraint=True, db_table=None,
                 graph=None, swappable=True, **kwargs):
        try:
            to._meta
        except AttributeError:
            assert isinstance(to, str), (
                "%s(%r) is invalid. First parameter to EdgeField must be "
                "either a model, a model name" %
                (self.__class__.__name__, to)
            )

        assert symmetrical is None, ("Edge models cannot be symmetric")
#       assert db_table is None, ("Edge models cannot link to a table")

        if through is not None:
            assert db_table is None, (
                "Cannot specify a db_table if an intermediary model is used."
            )

        #graph_name = kwargs['graph_name'] or model_name + other_end + edge_name

        #breakpoint()

        kwargs['rel'] = self.rel_class(
            self, to,
            related_name=related_name,
            related_query_name=related_query_name,
            limit_choices_to=limit_choices_to,
            symmetrical=False,
            through=through,
            through_fields=None,
            db_constraint=None,
        )
        self.has_null_arg = 'null' in kwargs

        super().__init__(**kwargs)

        self.db_table = db_table
        self.swappable = swappable

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_unique(**kwargs),
            *self._check_relationship_model(**kwargs),
            *self._check_ignored_options(**kwargs),
            *self._check_table_uniqueness(**kwargs),
        ]

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
        # Handle the simpler arguments.
        if self.db_table is not None:
            kwargs['db_table'] = self.db_table
        if self.remote_field.db_constraint is not True:
            kwargs['db_constraint'] = self.remote_field.db_constraint
        # Rel needs more work.
        if isinstance(self.remote_field.model, str):
            kwargs['to'] = self.remote_field.model
        else:
            kwargs['to'] = "%s.%s" % (
                self.remote_field.model._meta.app_label,
                self.remote_field.model._meta.object_name,
            )
        if getattr(self.remote_field, 'through', None) is not None:
            if isinstance(self.remote_field.through, str):
                kwargs['through'] = self.remote_field.through
            elif not self.remote_field.through._meta.auto_created:
                kwargs['through'] = "%s.%s" % (
                    self.remote_field.through._meta.app_label,
                    self.remote_field.through._meta.object_name,
                )

        # TTG don't think this should be here ...
        # If swappable is True, then see if we're actually pointing to the target
        # of a swap.
        swappable_setting = self.swappable_setting
        if swappable_setting is not None:
            # If it's already a settings reference, error.
            if hasattr(kwargs['to'], "setting_name"):
                if kwargs['to'].setting_name != swappable_setting:
                    raise ValueError(
                        "Cannot deconstruct a ManyToManyField pointing to a "
                        "model that is swapped in place of more than one model "
                        "(%s and %s)" % (kwargs['to'].setting_name, swappable_setting)
                    )

            kwargs['to'] = SettingsReference(
                kwargs['to'],
                swappable_setting,
            )

        return name, path, args, kwargs

    def db_check(self, connection):
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

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_unique(**kwargs),
            *self._check_relationship_model(**kwargs),
            *self._check_ignored_options(**kwargs),
            *self._check_table_uniqueness(**kwargs),
        ]

    def _check_unique(self, **kwargs):
        if self.unique:
            return [
                checks.Error(
                    'EdgeFields cannot be unique.',
                    obj=self,
                    id='fields.E330',
                )
            ]
        return []

    def _check_ignored_options(self, **kwargs):
        warnings = []

        if self.has_null_arg:
            warnings.append(
                checks.Warning(
                    'null has no effect on EdgeField.',
                    obj=self,
                    id='fields.W340',
                )
            )

        if self._validators:
            warnings.append(
                checks.Warning(
                    'EdgeField does not support validators.',
                    obj=self,
                    id='fields.W341',
                )
            )

        if (self.remote_field.limit_choices_to and self.remote_field.through and
                not self.remote_field.through._meta.auto_created):
            warnings.append(
                checks.Warning(
                    'limit_choices_to has no effect on EdgeField '
                    'with a through model.',
                    obj=self,
                    id='fields.W343',
                )
            )

        return warnings

    # Extensive checking on destination and through models here.  This was
    # copied from ManyToManyField and is likely to be useful in most cases.
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
                    "Field specifies a edge relation through model "
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
            # Set some useful local variables
            to_model = resolve_relation(from_model, self.remote_field.model)
            from_model_name = from_model._meta.object_name
            if isinstance(to_model, str):
                to_model_name = to_model
            else:
                to_model_name = to_model._meta.object_name
            relationship_model_name = self.remote_field.through._meta.object_name
            self_referential = from_model == to_model

            # Check symmetrical attribute.
            # Symmetrical Edge is not currently supported.
            if (self_referential and self.remote_field.symmetrical and
                    not self.remote_field.through._meta.auto_created):
                errors.append(
                    checks.Error(
                        'Edge fields must not be symmetrical.',
                        obj=self,
                        id='fields.E332',
                    )
                )

            # Count foreign keys in intermediate model
            if self_referential:
                seen_self = sum(
                    from_model == getattr(field.remote_field, 'model', None)
                    for field in self.remote_field.through._meta.fields
                )

                if seen_self > 2 and not self.remote_field.through_fields:
                    errors.append(
                        checks.Error(
                            "The model is used as an intermediate model by "
                            "'%s', but it has more than two edge keys "
                            "to '%s', which is ambiguous. You must specify "
                            "which two edge keys Django should use via the "
                            "through_fields keyword argument." % (self, from_model_name),
                            hint="Use through_fields to specify foreign keys Django should use.",
                            obj=self.remote_field.through,
                            id='fields.E333',
                        )
                    )

            else:
                # Count foreign keys in relationship model
                seen_from = sum(
                    from_model == getattr(field.remote_field, 'model', None)
                    for field in self.remote_field.through._meta.fields
                )
                seen_to = sum(
                    to_model == getattr(field.remote_field, 'model', None)
                    for field in self.remote_field.through._meta.fields
                )

                if seen_from > 1 and not self.remote_field.through_fields:
                    errors.append(
                        checks.Error(
                            ("The model is used as an intermediate model by "
                             "'%s', but it has more than one edge key "
                             "from '%s', which is ambiguous. You must specify "
                             "which edge key Django should use via the "
                             "through_fields keyword argument.") % (self, from_model_name),
                            hint=(
                                'If you want to create a recursive relationship, '
                                'use EdgeField("self", symmetrical=False, through="%s").'
                            ) % relationship_model_name,
                            obj=self,
                            id='fields.E334',
                        )
                    )

                if seen_to > 1 and not self.remote_field.through_fields:
                    errors.append(
                        checks.Error(
                            "The model is used as an intermediate model by "
                            "'%s', but it has more than one edge key "
                            "to '%s', which is ambiguous. You must specify "
                            "which edge key Django should use via the "
                            "through_fields keyword argument." % (self, to_model_name),
                            hint=(
                                'If you want to create a recursive relationship, '
                                'use ForeignKey("self", symmetrical=False, through="%s").'
                            ) % relationship_model_name,
                            obj=self,
                            id='fields.E335',
                        )
                    )

                if seen_from == 0 or seen_to == 0:
                    errors.append(
                        checks.Error(
                            "The model is used as an intermediate model by "
                            "'%s', but it does not have a edge key to '%s' or '%s'." % (
                                self, from_model_name, to_model_name
                            ),
                            obj=self.remote_field.through,
                            id='fields.E336',
                        )
                    )

        # Validate `through_fields`.
        if self.remote_field.through_fields is not None:
            # Validate that we're given an iterable of at least two items
            # and that none of them is "falsy".
            if not (len(self.remote_field.through_fields) >= 2 and
                    self.remote_field.through_fields[0] and self.remote_field.through_fields[1]):
                errors.append(
                    checks.Error(
                        "Field specifies 'through_fields' but does not provide "
                        "the names of the two link fields that should be used "
                        "for the relation through model '%s'." % qualified_model_name,
                        hint="Make sure you specify 'through_fields' as through_fields=('field1', 'field2')",
                        obj=self,
                        id='fields.E337',
                    )
                )

            # Validate the given through fields -- they should be actual
            # fields on the through model, and also be foreign keys to the
            # expected models.
            else:
                assert from_model is not None, (
                    "EdgeField with intermediate "
                    "tables cannot be checked if you don't pass the model "
                    "where the field is attached to."
                )

                source, through, target = from_model, self.remote_field.through, self.remote_field.model
                source_field_name, target_field_name = self.remote_field.through_fields[:2]

                for field_name, related_model in ((source_field_name, source),
                                                  (target_field_name, target)):

                    possible_field_names = []
                    for f in through._meta.fields:
                        if hasattr(f, 'remote_field') and getattr(f.remote_field, 'model', None) == related_model:
                            possible_field_names.append(f.name)
                    if possible_field_names:
                        hint = "Did you mean one of the following foreign keys to '%s': %s?" % (
                            related_model._meta.object_name,
                            ', '.join(possible_field_names),
                        )
                    else:
                        hint = None

                    try:
                        field = through._meta.get_field(field_name)
                    except exceptions.FieldDoesNotExist:
                        errors.append(
                            checks.Error(
                                "The intermediary model '%s' has no field '%s'."
                                % (qualified_model_name, field_name),
                                hint=hint,
                                obj=self,
                                id='fields.E338',
                            )
                        )
                    else:
                        if not (hasattr(field, 'remote_field') and
                                getattr(field.remote_field, 'model', None) == related_model):
                            errors.append(
                                checks.Error(
                                    "'%s.%s' is not a foreign key to '%s'." % (
                                        through._meta.object_name, field_name,
                                        related_model._meta.object_name,
                                    ),
                                    hint=hint,
                                    obj=self,
                                    id='fields.E339',
                                )
                            )

        return errors

    def _check_table_uniqueness(self, **kwargs):
        if isinstance(self.remote_field.through, str) or not self.remote_field.through._meta.managed:
            return []
        registered_tables = {
            model._meta.db_table: model
            for model in self.opts.apps.get_models(include_auto_created=True)
            if model != self.remote_field.through and model._meta.managed
        }
        edge_db_table = self.edge_db_table()
        model = registered_tables.get(edge_db_table)
        # The second condition allows multiple edge relations on a model if
        # some point to a through model that proxies another through model.
        if model and model._meta.concrete_model != self.remote_field.through._meta.concrete_model:
            if model._meta.auto_created:
                def _get_field_name(model):
                    for field in model._meta.auto_created._meta.many_to_many:
                        if field.remote_field.through is model:
                            return field.name
                opts = model._meta.auto_created._meta
                clashing_obj = '%s.%s' % (opts.label, _get_field_name(model))
            else:
                clashing_obj = model._meta.label
            return [
                checks.Error(
                    "The field's intermediary table '%s' clashes with the "
                    "table name of '%s'." % (edge_db_table, clashing_obj),
                    obj=self,
                    id='fields.E340',
                )
            ]
        return []


    def cast_db_type(self, connection):
#       if self.max_length is None:
#           return connection.ops.cast_char_field_without_max_length
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

    def NO_formfield(self, **kwargs):
        # In general, there should not be a formfield associated with an EdgeField.
        # This method should raise an exception if it is included in a form.
        defaults = { 'edge_attribute': self.edge_attribute }
        if self.null and not connection.features.edge_relevant_feature:
            defaults['empty_value'] = None
        defaults.update(kwargs)
        return super().formfield(**defaults)


# end fields.py
