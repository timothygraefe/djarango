"""
Accessors for related edge objects (copied from related_desciptors.py)

    related_desciptors:
    When a field defines a relation between two models, each model class provides
    an attribute to access related instances of the other model class (unless the
    reverse accessor has been disabled with related_name='+').

    Accessors are implemented as descriptors in order to customize access and
    assignment. This module defines the descriptor classes.

    Forward accessors follow foreign keys. Reverse accessors trace them back. For
    example, with the following models::

        class Parent(Model):
            pass

        class Child(Model):
            parent = ForeignKey(Parent, related_name='children')

     ``child.parent`` is a forward many-to-one relation. ``parent.children`` is a
    reverse many-to-one relation.

Edge descriptors:

Edge descriptors are most like many-to-many forward descriptors.  In Djarango,
edges are unidirectional.  It is possible to have a bidirectionaly relationship
between two vertices, but this must be accomplished by creating 2 edge
definitions, 1 in each direction.  It is allowable to use the same model for
the edge definition in each direction, the actual instances of the edge will
be distinct from each other.


There are three types of relations (many-to-one, one-to-one, and many-to-many)
and two directions (forward and reverse) for a total of six combinations.

But with Edges, all relations are m2m and forward.

    related_descriptors.py:
    5. Related objects manager for related instances on the forward or reverse
       sides of a many-to-many relation: ``ManyToManyDescriptor``.

       Many-to-many relations are symmetrical. The syntax of Django models
       requires declaring them on one side but that's an implementation detail.
       They could be declared on the other side without any change in behavior.
       Therefore the forward and reverse descriptors can be the same.

       If you're looking for ``ForwardManyToManyDescriptor`` or
       ``ReverseManyToManyDescriptor``, use ``ManyToManyDescriptor`` instead.

"""

from django.core.exceptions import FieldError
from django.db import connections, router, transaction
from django.db.models import Q, signals
from django.db.models.query import QuerySet
from django.utils.functional import cached_property

class ReverseEdgeDescriptor:
    """
    Accessor to the related objects manager on the reverse side of a
    many-to-one relation.

    In the example::

        class Child(Model):
            parent = ForeignKey(Parent, related_name='children')

    ``Parent.children`` is a ``ReverseEdgeDescriptor`` instance.

    Most of the implementation is delegated to a dynamically defined manager
    class built by ``create_forward_edge_to_edge_manager()`` defined below.
    """

    def __init__(self, rel):
        self.rel = rel
        self.field = rel.field

    @cached_property
    def related_manager_cls(self):
        related_model = self.rel.related_model

        return create_reverse_many_to_one_manager(
            related_model._default_manager.__class__,
            self.rel,
        )

    def __get__(self, instance, cls=None):
        """
        Get the related objects through the reverse relation.

        With the example above, when getting ``parent.children``:

        - ``self`` is the descriptor managing the ``children`` attribute
        - ``instance`` is the ``parent`` instance
        - ``cls`` is the ``Parent`` class (unused)
        """
        if instance is None:
            return self

        return self.related_manager_cls(instance)

    def _get_set_deprecation_msg_params(self):
        return (
            'reverse side of a related set',
            self.rel.get_accessor_name(),
        )

    def __set__(self, instance, value):
        raise TypeError(
            'Direct assignment to the %s is prohibited. Use %s.set() instead.'
            % self._get_set_deprecation_msg_params(),
        )


class EdgeDescriptor(ReverseEdgeDescriptor):
    """
    Accessor to the related objects manager on the forward and reverse sides of
    an edge relation (similar to many-to-many relation).

    Most of the implementation is delegated to a dynamically defined manager
    class built by ``create_forward_edge_to_edge_manager()`` defined below.
    """

    def __init__(self, rel, reverse=False):
        super().__init__(rel)

        self.reverse = reverse

    @property
    def through(self):
        # through is provided so that you have easy access to the through
        # model (Book.authors.through) for inlines, etc. This is done as
        # a property to ensure that the fully resolved value is returned.
        return self.rel.through

    @cached_property
    def related_manager_cls(self):
        related_model = self.rel.related_model if self.reverse else self.rel.model

        return create_forward_edge_to_edge_manager(
            related_model._default_manager.__class__,
            self.rel,
            reverse=self.reverse,
        )

    def _get_set_deprecation_msg_params(self):
        return (
            '%s side of a many-to-many set' % ('reverse' if self.reverse else 'forward'),
            self.rel.get_accessor_name() if self.reverse else self.field.name,
        )


def create_forward_edge_to_edge_manager(superclass, rel, reverse):
    """
    Create a manager for the either side of an edge-to-edge relation.

    This manager subclasses another manager, generally the default manager of
    the related model, and adds behaviors specific to edge-to-edge relations.
    """

    class EdgeRelatedManager(superclass):
        def __init__(self, instance=None):
            super().__init__()

            self.instance = instance

            if not reverse:
                self.model = rel.model
                self.query_field_name = rel.field.related_query_name()
                self.prefetch_cache_name = rel.field.name
                self.source_field_name = rel.field.e2e_field_name()
                self.target_field_name = rel.field.e2e_reverse_field_name()
                self.symmetrical = rel.symmetrical
            else:
                self.model = rel.related_model
                self.query_field_name = rel.field.name
                self.prefetch_cache_name = rel.field.related_query_name()
                self.source_field_name = rel.field.e2e_reverse_field_name()
                self.target_field_name = rel.field.e2e_field_name()
                self.symmetrical = False

            self.through = rel.through
            self.reverse = reverse

            self.source_field = self.through._meta.get_field(self.source_field_name)
            self.target_field = self.through._meta.get_field(self.target_field_name)

            self.core_filters = {}
            self.pk_field_names = {}
            for lh_field, rh_field in self.source_field.related_fields:
                core_filter_key = '%s__%s' % (self.query_field_name, rh_field.name)
                self.core_filters[core_filter_key] = getattr(instance, rh_field.attname)
                self.pk_field_names[lh_field.name] = rh_field.name

            self.related_val = self.source_field.get_foreign_related_value(instance)
            if None in self.related_val:
                raise ValueError('"%r" needs to have a value for field "%s" before '
                                 'this many-to-many relationship can be used.' %
                                 (instance, self.pk_field_names[self.source_field_name]))
            # Even if this relation is not to pk, we require still pk value.
            # The wish is that the instance has been already saved to DB,
            # although having a pk value isn't a guarantee of that.
            if instance.pk is None:
                raise ValueError("%r instance needs to have a primary key value before "
                                 "a many-to-many relationship can be used." %
                                 instance.__class__.__name__)

        def __call__(self, *, manager):
            manager = getattr(self.model, manager)
            manager_class = create_forward_edge_to_edge_manager(manager.__class__, rel, reverse)
            return manager_class(instance=self.instance)
        do_not_call_in_templates = True

        def _build_remove_filters(self, removed_vals):
            filters = Q(**{self.source_field_name: self.related_val})
            # No need to add a subquery condition if removed_vals is a QuerySet without
            # filters.
            removed_vals_filters = (not isinstance(removed_vals, QuerySet) or
                                    removed_vals._has_filters())
            if removed_vals_filters:
                filters &= Q(**{'%s__in' % self.target_field_name: removed_vals})
            if self.symmetrical:
                symmetrical_filters = Q(**{self.target_field_name: self.related_val})
                if removed_vals_filters:
                    symmetrical_filters &= Q(
                        **{'%s__in' % self.source_field_name: removed_vals})
                filters |= symmetrical_filters
            return filters

        def _apply_rel_filters(self, queryset):
            """
            Filter the queryset for the instance this manager is bound to.
            """
            queryset._add_hints(instance=self.instance)
            if self._db:
                queryset = queryset.using(self._db)
            return queryset._next_is_sticky().filter(**self.core_filters)

        def _remove_prefetched_objects(self):
            try:
                self.instance._prefetched_objects_cache.pop(self.prefetch_cache_name)
            except (AttributeError, KeyError):
                pass  # nothing to clear from cache

        def get_queryset(self):
            try:
                return self.instance._prefetched_objects_cache[self.prefetch_cache_name]
            except (AttributeError, KeyError):
                queryset = super().get_queryset()
                return self._apply_rel_filters(queryset)

        def get_prefetch_queryset(self, instances, queryset=None):
            if queryset is None:
                queryset = super().get_queryset()

            queryset._add_hints(instance=instances[0])
            queryset = queryset.using(queryset._db or self._db)

            query = {'%s__in' % self.query_field_name: instances}
            queryset = queryset._next_is_sticky().filter(**query)

            # M2M: need to annotate the query in order to get the primary model
            # that the secondary model was actually related to. We know that
            # there will already be a join on the join table, so we can just add
            # the select.

            # For non-autocreated 'through' models, can't assume we are
            # dealing with PK values.
            fk = self.through._meta.get_field(self.source_field_name)
            join_table = fk.model._meta.db_table
            connection = connections[queryset.db]
            qn = connection.ops.quote_name
            queryset = queryset.extra(select={
                '_prefetch_related_val_%s' % f.attname:
                '%s.%s' % (qn(join_table), qn(f.column)) for f in fk.local_related_fields})
            return (
                queryset,
                lambda result: tuple(
                    getattr(result, '_prefetch_related_val_%s' % f.attname)
                    for f in fk.local_related_fields
                ),
                lambda inst: tuple(
                    f.get_db_prep_value(getattr(inst, f.attname), connection)
                    for f in fk.foreign_related_fields
                ),
                False,
                self.prefetch_cache_name,
                False,
            )

        def add(self, *objs, through_defaults=None):
            self._remove_prefetched_objects()
            db = router.db_for_write(self.through, instance=self.instance)
            with transaction.atomic(using=db, savepoint=False):
                self._add_items(
                    self.source_field_name, self.target_field_name, *objs,
                    through_defaults=through_defaults,
                )
                # If this is a symmetrical m2m relation to self, add the mirror
                # entry in the m2m table. `through_defaults` aren't used here
                # because of the system check error fields.E332: Many-to-many
                # fields with intermediate tables must not be symmetrical.
                if self.symmetrical:
                    self._add_items(self.target_field_name, self.source_field_name, *objs)
        add.alters_data = True

        def remove(self, *objs):
            self._remove_prefetched_objects()
            self._remove_items(self.source_field_name, self.target_field_name, *objs)
        remove.alters_data = True

        def clear(self):
            db = router.db_for_write(self.through, instance=self.instance)
            with transaction.atomic(using=db, savepoint=False):
                signals.e2e_changed.send(
                    sender=self.through, action="pre_clear",
                    instance=self.instance, reverse=self.reverse,
                    model=self.model, pk_set=None, using=db,
                )
                self._remove_prefetched_objects()
                filters = self._build_remove_filters(super().get_queryset().using(db))
                self.through._default_manager.using(db).filter(filters).delete()

                signals.e2e_changed.send(
                    sender=self.through, action="post_clear",
                    instance=self.instance, reverse=self.reverse,
                    model=self.model, pk_set=None, using=db,
                )
        clear.alters_data = True

        def set(self, objs, *, clear=False, through_defaults=None):
            # Force evaluation of `objs` in case it's a queryset whose value
            # could be affected by `manager.clear()`. Refs #19816.
            objs = tuple(objs)

            db = router.db_for_write(self.through, instance=self.instance)
            with transaction.atomic(using=db, savepoint=False):
                if clear:
                    self.clear()
                    self.add(*objs, through_defaults=through_defaults)
                else:
                    old_ids = set(self.using(db).values_list(self.target_field.target_field.attname, flat=True))

                    new_objs = []
                    for obj in objs:
                        fk_val = (
                            self.target_field.get_foreign_related_value(obj)[0]
                            if isinstance(obj, self.model) else obj
                        )
                        if fk_val in old_ids:
                            old_ids.remove(fk_val)
                        else:
                            new_objs.append(obj)

                    self.remove(*old_ids)
                    self.add(*new_objs, through_defaults=through_defaults)
        set.alters_data = True

        def create(self, *, through_defaults=None, **kwargs):
            db = router.db_for_write(self.instance.__class__, instance=self.instance)
            new_obj = super(EdgeRelatedManager, self.db_manager(db)).create(**kwargs)
            self.add(new_obj, through_defaults=through_defaults)
            return new_obj
        create.alters_data = True

        def get_or_create(self, *, through_defaults=None, **kwargs):
            db = router.db_for_write(self.instance.__class__, instance=self.instance)
            obj, created = super(EdgeRelatedManager, self.db_manager(db)).get_or_create(**kwargs)
            # We only need to add() if created because if we got an object back
            # from get() then the relationship already exists.
            if created:
                self.add(obj, through_defaults=through_defaults)
            return obj, created
        get_or_create.alters_data = True

        def update_or_create(self, *, through_defaults=None, **kwargs):
            db = router.db_for_write(self.instance.__class__, instance=self.instance)
            obj, created = super(EdgeRelatedManager, self.db_manager(db)).update_or_create(**kwargs)
            # We only need to add() if created because if we got an object back
            # from get() then the relationship already exists.
            if created:
                self.add(obj, through_defaults=through_defaults)
            return obj, created
        update_or_create.alters_data = True

        def _add_items(self, source_field_name, target_field_name, *objs, through_defaults=None):
            # source_field_name: the PK fieldname in join table for the source object
            # target_field_name: the PK fieldname in join table for the target object
            # *objs - objects to add. Either object instances, or primary keys of object instances.
            through_defaults = through_defaults or {}

            # If there aren't any objects, there is nothing to do.
            from django.db.models import Model
            if objs:
                new_ids = set()
                for obj in objs:
                    if isinstance(obj, self.model):
                        if not router.allow_relation(obj, self.instance):
                            raise ValueError(
                                'Cannot add "%r": instance is on database "%s", value is on database "%s"' %
                                (obj, self.instance._state.db, obj._state.db)
                            )
                        fk_val = self.through._meta.get_field(
                            target_field_name).get_foreign_related_value(obj)[0]
                        if fk_val is None:
                            raise ValueError(
                                'Cannot add "%r": the value for field "%s" is None' %
                                (obj, target_field_name)
                            )
                        new_ids.add(fk_val)
                    elif isinstance(obj, Model):
                        raise TypeError(
                            "'%s' instance expected, got %r" %
                            (self.model._meta.object_name, obj)
                        )
                    else:
                        new_ids.add(obj)

                db = router.db_for_write(self.through, instance=self.instance)
                vals = (self.through._default_manager.using(db)
                        .values_list(target_field_name, flat=True)
                        .filter(**{
                            source_field_name: self.related_val[0],
                            '%s__in' % target_field_name: new_ids,
                        }))
                new_ids.difference_update(vals)

                with transaction.atomic(using=db, savepoint=False):
                    if self.reverse or source_field_name == self.source_field_name:
                        # Don't send the signal when we are inserting the
                        # duplicate data row for symmetrical reverse entries.
                        signals.e2e_changed.send(
                            sender=self.through, action='pre_add',
                            instance=self.instance, reverse=self.reverse,
                            model=self.model, pk_set=new_ids, using=db,
                        )

                    # Add the ones that aren't there already
                    self.through._default_manager.using(db).bulk_create([
                        self.through(**through_defaults, **{
                            '%s_id' % source_field_name: self.related_val[0],
                            '%s_id' % target_field_name: obj_id,
                        })
                        for obj_id in new_ids
                    ])

                    if self.reverse or source_field_name == self.source_field_name:
                        # Don't send the signal when we are inserting the
                        # duplicate data row for symmetrical reverse entries.
                        signals.e2e_changed.send(
                            sender=self.through, action='post_add',
                            instance=self.instance, reverse=self.reverse,
                            model=self.model, pk_set=new_ids, using=db,
                        )

        def _remove_items(self, source_field_name, target_field_name, *objs):
            # source_field_name: the PK colname in join table for the source object
            # target_field_name: the PK colname in join table for the target object
            # *objs - objects to remove. Either object instances, or primary
            # keys of object instances.
            if not objs:
                return

            # Check that all the objects are of the right type
            old_ids = set()
            for obj in objs:
                if isinstance(obj, self.model):
                    fk_val = self.target_field.get_foreign_related_value(obj)[0]
                    old_ids.add(fk_val)
                else:
                    old_ids.add(obj)

            db = router.db_for_write(self.through, instance=self.instance)
            with transaction.atomic(using=db, savepoint=False):
                # Send a signal to the other end if need be.
                signals.e2e_changed.send(
                    sender=self.through, action="pre_remove",
                    instance=self.instance, reverse=self.reverse,
                    model=self.model, pk_set=old_ids, using=db,
                )
                target_model_qs = super().get_queryset()
                if target_model_qs._has_filters():
                    old_vals = target_model_qs.using(db).filter(**{
                        '%s__in' % self.target_field.target_field.attname: old_ids})
                else:
                    old_vals = old_ids
                filters = self._build_remove_filters(old_vals)
                self.through._default_manager.using(db).filter(filters).delete()

                signals.e2e_changed.send(
                    sender=self.through, action="post_remove",
                    instance=self.instance, reverse=self.reverse,
                    model=self.model, pk_set=old_ids, using=db,
                )

    return EdgeRelatedManager

# edge_descriptors.py
