# MiniRecord ORM DSL

This executable example explores how a Rails-inspired ORM can fit Hoomer's
programming model without introducing classes, inheritance, hidden state, or an
implicit block receiver.

Ruby on Rails commonly expresses a query through methods on a model class:

```ruby
User.where(active: true).limit(10)
```

Hoomer keeps the model and query as explicit data transformed by package
functions:

```hmr
query = Database.all(user_model)
query = Database.where(query, field: "active", equals: true)
query = Database.limit(query, 10)
Database.execute(query)
```

Reflection maps an ordinary record struct to a table model. Fallible inserts
return either the original record or a declared error value, so callers can
choose between full matching and compact inline `when`. The transaction API
demonstrates how a library can provide a readable closure through a final
`&block` parameter without special ORM grammar.

Run the example from the repository root:

```sh
python3 -m hoomer.main examples/orm_dsl/application
```
