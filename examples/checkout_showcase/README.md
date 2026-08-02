# Checkout syntax showcase

This is the same checkout application written in Ruby and Hoomer. Both versions
normalize a customer, validate an order, reserve inventory, calculate a discount,
charge a payment, reward loyalty, and render success or ordinary error values.

The examples intentionally cover the practical application syntax shared by the
two languages. They are not a claim to cover every Ruby feature: Ruby's classes,
inheritance, exceptions, metaprogramming, regular expressions, hashes, and fibers
do not have direct equivalents in Hoomer's current small grammar.

Run the Ruby version:

```sh
ruby examples/checkout_showcase/ruby/checkout.rb
```

Run the Hoomer version:

```sh
python3 -m hoomer.main examples/checkout_showcase/hoomer/checkout
```

## Syntax exercised

| Idea | Ruby | Hoomer |
| --- | --- | --- |
| Namespaces and imports | `module`, `require_relative` | `package`, `import`, `as` |
| Data | `Struct.new`, keyword construction | `struct`, named field construction |
| Functions | methods, defaults, keywords | `fn`, defaults, named parameters |
| Visibility | module API | `pub` package API |
| Error flow | ordinary result structs and `case` | declared error values, `!`, `try`, and `when` |
| Branching | `if`, `elsif`, `else`, `case` | `if`, `elsif`, `else`, full and inline `when` |
| Collections | arrays, `each`, `sum` | lists, `for` |
| Ranges | `1..3` | `1..3` |
| Blocks | `do ... end`, `yield` | `do ... end`, final `&block` parameter |
| Text | interpolation, `strip`, `downcase` | interpolation |
| State | struct field assignment | struct field assignment |
| Introspection | `class`, `members`, `method` | built-in `reflection(value)` |
| Control flow | `return`, `next`, implicit method values | early `return`, `continue`, implicit function and branch values |
| Other values | numbers, strings, booleans, `nil`, arrays | numbers, strings, booleans, `nil`, lists |

The deliberately different lines are useful design evidence. Ruby's dense
collection helpers make it shorter. Hoomer's strict booleans, exhaustive
matching, and visible fallible-result handling make more of the control flow
readable without knowing conventions outside the file.
