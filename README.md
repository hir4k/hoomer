# Hoomer Language Design Philosophy

**Version:** 0.3
**Extension:** `.hmr`

## Try the interpreter

Hoomer requires Python 3.12 or newer. From this repository, run the complete
accounts/application example with:

```sh
python3 -m hoomer.main examples/application
```

The output starts with:

```text
Welcome Hirak!
ID: 10
Name: Hirak
```

Install the local package to make the shorter command available:

```sh
python3 -m pip install -e .
hoomer examples/application
hoomer check examples/application
hoomer repl
```

Run the test suite with:

```sh
python3 -m unittest discover -v
```

The prototype implements literals and interpolation, variables and explicit
public constants, default and named parameters, structs and error values,
field and indexed access, packages, imports, strict boolean operators,
`if`/`elsif`, exhaustive and inline `when` expressions, `try` propagation,
lists, maps, inclusive ranges, `for` and `while` loops, `break` and `continue`,
reflection, parameterized `do` closures, source-aware error traces, and a REPL.

`print` and the `reflection_*` functions are available without imports because
output and runtime metadata are essential language capabilities.

## Example programs

The `examples` directory includes standalone programs for familiar algorithms:

- [`fizz_buzz`](examples/fizz_buzz) prints FizzBuzz from 1 through 100.
- [`factorial`](examples/factorial) calculates factorials recursively.
- [`fibonacci`](examples/fibonacci) prints the first 12 Fibonacci numbers.
- [`prime_numbers`](examples/prime_numbers) finds prime numbers up to 50.
- [`user`](examples/user) imports and uses a struct from another package.
- [`inline_when`](examples/inline_when) demonstrates compact result
  filtering with an explicit lazy fallback.
- [`checkout_showcase`](examples/checkout_showcase/README.md) implements the same
  realistic checkout workflow in Ruby and Hoomer as a practical syntax comparison.
- [`orm_dsl`](examples/orm_dsl/README.md) builds an executable Rails-inspired
  model, transaction, persistence, and query DSL from ordinary Hoomer features.

Run any of them from the repository root:

```sh
python3 -m hoomer.main examples/fizz_buzz
python3 -m hoomer.main examples/factorial
python3 -m hoomer.main examples/fibonacci
python3 -m hoomer.main examples/prime_numbers
python3 -m hoomer.main examples/user
python3 -m hoomer.main examples/inline_when
python3 -m hoomer.main examples/checkout_showcase/hoomer/checkout
python3 -m hoomer.main examples/orm_dsl/application
```

---

# 1. Introduction

Hoomer is a programming language designed around one core idea:

> Programming languages should be optimized for humans.

The goal of Hoomer is not to create the fastest language, the smallest binary, or the most mathematically pure language.

The goal is to create a language where:

- Reading code feels natural.
- Writing code feels enjoyable.
- The language disappears behind the idea being expressed.
- Common programming tasks require less ceremony.
- Libraries can create beautiful APIs without changing the language.

Hoomer is a dynamic, interpreted, reflective language focused on simplicity, expressiveness, and developer happiness.

---

# 2. Design Philosophy

## 2.1 Humans First

A programmer spends more time reading code than writing code.

Therefore, Hoomer optimizes for:

- Clear naming
- Minimal syntax noise
- Predictable behavior
- Easy-to-understand abstractions

Code should communicate intent.

Example:

```hmr
user = find_user!(email)

when user
    User as account:
        print account.name

    nil:
        print "User not found"

    else:
        print "Unexpected result"
end
```

The code should explain itself.

---

# 3. Core Principles

## 3.1 Small Core Language

Hoomer should have a small number of concepts.

The language core provides:

- Packages
- Functions
- Structs
- Values
- Pattern matching
- Printing
- Reflection
- Blocks
- Imports

The core does not bundle convenience packages such as text helpers. Reusable
APIs belong in independently versioned packages that will be installed by the
Hoomer package manager.

The language should not add features only because a framework needs them.

---

## 3.2 No Hidden Magic

Hoomer avoids invisible behavior.

A programmer should understand:

- Where data comes from.
- Where functions come from.
- How state changes.
- How errors flow.

Imports are explicit.

State is explicit.

Control flow is explicit.

---

# 4. Programming Model

Hoomer follows:

> Packages organize behavior. Structs hold data. Functions transform data.

There are no:

- Classes
- Inheritance
- Objects with hidden methods
- Global mutable variables

---

# 5. Packages

A package is a directory of `.hmr` files that share one semantic namespace.
Every file starts with the same package header, which extends to EOF and does
not need a closing `end`.

```text
kenekoi/
    hoomer.toml
    accounts/
        user.hmr
        authentication.hmr
    passwords/
        password.hmr
```

```hmr
# kenekoi/accounts/user.hmr
package Accounts

pub struct User
    name,
    email,
end

fn find_user(id)
end
```

```hmr
# kenekoi/accounts/authentication.hmr
package Accounts

import kenekoi/passwords

pub fn login(id, password)
    user = find_user(id)
    return Passwords.matches(user, password)
end
```

Imports cross package boundaries, not file boundaries. Imports are file-scoped,
so a sibling file must declare an external dependency when it uses that package
directly. Private functions, structs, errors, and constants are shared throughout
their own package; `pub` exposes them to other packages.

The directory containing `hoomer.toml` is the project root. Its snake_case
directory name begins every project-local import path. In the example above,
`kenekoi/accounts` and `kenekoi/passwords` are distinct runtime identities.
Paths are unquoted because static imports are declarations, not runtime strings.
An import whose first segment is not the project root is resolved as an external
package from the interpreter's package search paths. The package manager will
eventually populate those paths from the project's locked dependencies. Hoomer
does not reserve import paths for bundled convenience packages.

Package loading is inert. Package scope accepts imports, inert constants,
structs, and functions, but rejects printing, ordinary assignments, calls,
branches, and loops. Constants cannot hide load-time calls:

```hmr
MAX_LOGIN_ATTEMPTS = 5       # valid
DATABASE = Database.connect() # invalid
```

Running a package directory loads every `.hmr` file and invokes its private,
zero-argument `main` function when present. A library package without `main`
loads successfully without output.

```hmr
package Greeting


fn main
    print "Hello"
end
```

```sh
hoomer greeting
hoomer check greeting
```

An individual package file is not executable because it may depend on sibling
files. Use `hoomer greeting`, not `hoomer greeting/main.hmr`.

---

# 6. Naming Convention

Naming is part of the language design.

The shape of a name should tell the reader what it represents.

## Packages

PascalCase:

```text
Authentication
LoginService
DatabaseConnection
```

---

## Structs

PascalCase:

```text
User
DatabaseError
HttpResponse
```

---

## Functions

snake_case:

```text
create_user()
find_by_email()
send_notification()
```

---

## Variables

snake_case:

```text
user_name
database_connection
current_user
```

---

## Fields

snake_case:

```text
first_name
created_at
updated_at
```

---

## Constants

UPPER_SNAKE_CASE:

```text
MAX_CONNECTIONS
DEFAULT_TIMEOUT
API_VERSION
```

---

# 7. Structs

Structs represent data.

Example:

```hmr
struct User

    name,
    email,
    active: true,

end
```

Creating:

```hmr
user = User(
    name: "Hirak",
    email: "hirak@example.com",
)
```

Structs support:

- Default values
- Named fields
- Reflection

Fields are comma-separated. A field without a default is required; a field with
`: default` is optional. Construction always uses parentheses and `:` named
fields—positional struct construction is invalid. Small definitions may stay on
one line: `struct Point x, y end`.

---

# 8. No Classes

Hoomer does not use classes.

Instead:

Data:

```hmr
struct User
    name
end
```

Behavior:

```hmr
package Users

fn activate(user)
    user.active = true
    return user
end
```

Behavior is separated from data.

---

# 9. Variables

Variables are simple bindings.

Example:

```hmr
name = "Hirak"

age = 26

active = true
```

The language is dynamic.

Types exist at runtime through values and reflection.

---

# 10. Nil

Hoomer allows `nil`.

`nil` represents:

> No value exists.

Example:

```hmr
avatar = nil
```

Nil is not an error.

It is a valid value.

Examples:

```text
User exists but has no avatar
Database search found nothing
Optional configuration is disabled
```

---

# 11. Errors

Errors are values.

Hoomer does not use exceptions.

Example:

```hmr
error DatabaseError
    message,
end

failure = DatabaseError(message: "Connection failed")
```

A function may return:

```text
User
nil
DatabaseError
ValidationError
```

The programmer handles values using pattern matching.

---

# 12. Fallible Functions

Functions that may fail can use `!`.

Example:

```hmr
save_user!
```

The symbol is an enforced communication and tooling contract.

It tells the reader:

> Inspect this function's ordinary return value before assuming success.

Example:

```hmr
result = save_user!(user)
```

The programmer can handle the result:

```hmr
when result
    User as user:
        print user.name

    DatabaseError as error:
        print error.message

    else:
        print "Unexpected result"
end
```

An ordinary call returns its success value or its error value unchanged. A
fallible function can use `try` when it only wants to handle success:

```hmr
fn load_profile!()
    user = try load_user!()
    try load_preferences!(user)
end
```

If the called function produces an error, `try` immediately returns that same
error from the current `!` function. It does not terminate the process. Without
`try`, the caller can store or match the raw result. A fallible result cannot be
silently discarded.

Error values retain compact creation and propagation frames for diagnostics and
tooling. `print error` displays the error value.

---

# 13. Boolean Conditions

Hoomer uses descriptive function names instead of a special `?` suffix.

Example:

```hmr
fn is_active(user)
    user.active
end
```

Usage:

```hmr
if is_active(user)
    print "Active"
end
```

Conditions accept only `true` or `false`. Numbers, strings, lists, maps, and
`nil` are not implicitly truthy or falsey.

`and` and `or` short-circuit, and `not` negates a boolean. Exact runtime type
checks use `is` and `is not`:

```hmr
if value is User and value.active
    print value.name
end
```

---

# 14. Pattern Matching

Pattern matching is done using `when`.

Example:

```hmr
when result
    User as user:
        print user.name

    DatabaseError as error:
        print error.message

    nil:
        print "Nothing found"

    else as unexpected:
        print "Unknown: {unexpected}"
end
```

The `as` keyword creates a branch-local name. A final `else` branch is required
so new outcomes cannot silently pass through unmatched. Use `else as value` when
the unmatched value is needed inside that branch.

`when` is an expression. Its selected branch contributes its final value:

```hmr
database = when connect_database!()
    DatabaseConnection as connection:
        connection
    DatabaseConnectionFailure as error:
        print error.message
        nil
    else:
        nil
end
```

When the `when` expression is the final expression of a function or `do` block,
its selected branch becomes that callable's implicit return value. An explicit
`return` still exits early.

When only one outcome matters, the inline form preserves a matching value and
requires an explicit fallback. Write `else nil` when absence is intentional:

```hmr
connection = connect_database!() when DatabaseConnection else nil
```

The fallback is evaluated lazily only when the pattern does not match:

```hmr
customer = find_customer!() when Customer else GuestCustomer()
```

The expression before `when` runs exactly once. Inline `when` deliberately
discards the original nonmatching value, so use the full form whenever an error
needs to be logged, transformed, or returned.

---

# 15. Why `as`

Hoomer avoids unnecessary variable creation.

Instead of:

```hmr
User user
```

Hoomer prefers:

```hmr
when result
    User as user:
        print user.name
    else:
        nil
end
```

Each binding describes only the value matched by its own branch.

---

# 16. Functions

Functions are the main unit of behavior.

Example:

```hmr
fn greet(name)
    "Hello {name}"
end
```

Parameters may be positional or named. Positional parameters are always
required; a default makes a parameter named:

```hmr
fn connect(
    service,
    host:,
    retries: 3,
    port: 5432,
)
    # ...
end

connect("database", host: "localhost")
```

The three parameter forms are `name` for required positional, `name:` for
required named, and `name: default` for named with a default. Required
positional parameters appear before named parameters, and required named
parameters appear before named defaults. Calls use the same `name: value`
spelling as struct construction. `=` remains assignment rather than carrying a
second meaning inside calls.

An ordinary call may omit parentheses only when the entire statement is that
call—`greet "Hirak"` and `greet("Hirak")` are equivalent as standalone lines.
Nested calls, assigned calls, returned calls, and struct construction require
parentheses. This keeps expression boundaries visible.

Multiple positional and named arguments use commas in the same order as a
parenthesized call:

```hmr
some_function arg1, arg2, keywordarg: value
```

Strings are combined through interpolation, never with `+`:

```hmr
message = "Hello {name}"
```

A parameterless block function may omit its empty parameter list. This keeps
declarative APIs, such as a migration library, focused on their domain:

```hmr
fn change
    field "name", "string"
    field "username", "string"
    field "age", "int"
end
```

Here, `field` is an ordinary function supplied by the library. A migration
runner invokes the definition with `change()`; empty parentheses remain
required at the call site because `change` by itself refers to the function.

The final expression of a block function is returned implicitly. `return`
remains available for an early exit:

```hmr
fn validate(name)
    if name == ""
        return "Invalid"
    end

    "Valid"
end
```

Every function uses the same body-and-`end` form, including functions with one
expression. An empty body, bare `return`, or final action such as `print`
produces `nil`.

---

# 17. One Function per Name

A function name identifies exactly one definition in its scope. Hoomer does not
perform overload selection.

Example:

```hmr
fn greet(name: "World")
    "Hello {name}"
end
```

Default and named parameters cover optional inputs. Genuinely different
behavior should use a different descriptive name.

---

# 18. Imports

Imports bring names from another package into the current scope.

Every import uses a connected, slash-separated `snake_case` package path:

```hmr
import kenekoi/accounts
```

The imported package's declaration supplies its local name, so this makes
`Accounts` available. Use `as` when two paths declare the same package name or
when a clearer local name helps:

```hmr
import accounts as InstalledAccounts
import kenekoi/accounts as ProjectAccounts
```

Import selected members:

```hmr
import kenekoi/accounts:
    User,
    find_user
```

Imports identify package directories, never source files. Quoted, relative,
absolute, dotted, and whitespace-separated paths are invalid:

```hmr
import "kenekoi/accounts" # invalid: static paths are not strings
import ../accounts        # invalid: paths are never relative
import kenekoi / accounts # invalid: whitespace around `/`
```

Imports remain file-scoped. Same-package declarations need no import, while
every file using an external package declares that dependency itself:

```hmr
import validation:
    validate_email
```

Imports are explicit.

---

# 19. Blocks

Blocks allow libraries to create readable APIs.

Example:

```hmr
Database.transaction() do(transaction)
    transaction.save(user)
end
```

A block is a closure supplied to a function's final `&` parameter:

```hmr
fn visit(users, &action)
    for user in users
        action(user)
    end
end

visit(users) do(user)
    print user.name
end

visit(users, &show_user)
```

The block can read and update variables from its surrounding lexical scope.
The same API accepts either an inline `do(...) ... end` block or an existing
function passed with `&name`.

The language does not need special syntax for:

- Web frameworks
- Testing frameworks
- UI libraries
- Database libraries

Libraries build these.

---

# 20. Collections and Loops

List literals are comma-separated and may span lines. Lists support indexed
reads and assignments. Inclusive integer ranges use `first..last`; they count
up or down depending on the bounds. `for` visits each item, and `continue`
skips directly to the next one.

```hmr
users = [
    User(name: "Hirak"),
    User(name: "Rahul"),
]

for user in users
    if user.active == false
        continue
    end

    print user.name
end
```

Use a range when the loop visits consecutive whole numbers:

```hmr
for number in 0..10
    print number
end
```

Maps associate stable scalar keys with arbitrary values. They preserve insertion
order for printing and iteration, while equality compares their contents rather
than their order.

```hmr
field_name = "email"
user = {
    "name": "Hirak",
    field_name: "hirak@example.com",
}

print user["name"]
print user["city"] # nil

user["city"] = "Guwahati"
```

A quoted key is a string. An unquoted key such as `field_name` evaluates that
variable. Map keys may be strings, numbers, booleans, or `nil`; mutable structs
and collections cannot be keys because changing one must never make an existing
entry unreachable.

`in` checks whether a map contains a key, including a key whose stored value is
`nil`:

```hmr
if "city" in user
    print "A city was provided"
end
```

It also checks values in lists and ranges and substrings in strings. `while`
repeats while its condition is exactly `true`; `break` exits the nearest loop.

A map loop can visit keys alone or bind each key and value:

```hmr
for key in user
    print key
end

for key, value in user
    print "{key}: {value}"
end
```

---

# 21. Reflection

Hoomer supports runtime reflection.

Programs can inspect:

- Values
- Structs
- Packages
- Functions

Example:

```hmr
info = reflection(user)

print info.fields
```

Package reflection separates the declared name from its runtime import identity:

```hmr
import kenekoi/accounts

info = reflection(Accounts)
print info.name # Accounts
print info.path # kenekoi/accounts
```

Reflection enables:

- ORM libraries
- Serialization
- Frameworks
- Developer tools

Frameworks that genuinely need dynamic behavior can use `reflection_load`,
`reflection_get`, `reflection_set`, and `reflection_call`. Static `import` and
direct calls remain the normal, clearer choice for application code. Use
`reflection(value)` for ordinary inspection.

---

# 22. Constants

Constants use UPPER_SNAKE_CASE.

Example:

```hmr
pub MAX_CONNECTIONS = 100
DEFAULT_TIMEOUT = 30
```

Constants are immutable. A package constant is private unless its declaration
starts with `pub`.

---

# 23. State Philosophy

Hoomer avoids hidden mutable state.

No:

```text
@variable
global mutable variables
class instance state
```

State belongs to structs.

Example:

```hmr
struct Counter
    value: 0,
end
```

State is represented as data.

---

# 24. Language Goals

Hoomer aims to combine:

- Ruby's joy of writing
- Elixir's values and concurrency philosophy
- Python's readability
- Go's simplicity
- Functional programming concepts

while avoiding:

- Excessive syntax
- Hidden magic
- Complex type systems
- Boilerplate

---

# 25. Prototype Interpreter

The first implementation is written in Python.

The prototype includes:

1. Lexer
2. Parser
3. AST
4. Interpreter
5. Runtime values
6. Packages
7. Structs
8. Functions
9. Pattern matching

The first goal is not performance.

The first goal is proving:

> Does Hoomer feel good to write?

---

# 26. Final Vision

Hoomer is built around a simple belief:

> The best programming language is the one that lets humans express ideas naturally.

A language should not make programmers think like machines.

The machine should work hard so humans can think clearly.
