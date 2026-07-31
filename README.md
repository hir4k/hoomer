# Hoomer Language Design Philosophy

**Version:** 0.1  
**Extension:** `.hmr`

## Try the interpreter

Hoomer requires Python 3.12 or newer. From this repository, run the required
MVP example with:

```sh
python -m hoomer.main run examples/user.hmr
```

Expected output:

```text
Hello Hirak
```

Install the local package to make the shorter command available:

```sh
python -m pip install -e .
hoomer run examples/user.hmr
hoomer repl
```

Run the test suite with:

```sh
python -m unittest discover -v
```

The MVP implements literals and interpolation, variables and constants,
functions (including automatic return and arity overloads), structs, field
access and assignment, modules, imports, `if`/`elsif`, `when` matching, function
markers, reflection, `do` blocks, source-aware errors, and an interactive REPL.

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
user = find_user(email)

when user as account

    User
        print account.name

    nil
        print "User not found"

end
```

The code should explain itself.

---

# 3. Core Principles

## 3.1 Small Core Language

Hoomer should have a small number of concepts.

The language provides:

- Modules
- Functions
- Structs
- Values
- Pattern matching
- Reflection
- Blocks
- Imports

Everything else should be built as libraries.

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

> Modules organize behavior. Structs hold data. Functions transform data.

There are no:

- Classes
- Inheritance
- Objects with hidden methods
- Global mutable variables

---

# 5. Modules

Modules are declarative namespaces: they describe what exists, but they do not
perform application actions while loading.

Example:

```hmr
module Authentication.LoginService
```

Modules contain:

- Imports
- Constants
- Functions
- Structs

This is valid because every module-level statement is a declaration:

Example:

```hmr
module Accounts

MAX_LOGIN_ATTEMPTS = 5


struct User

    name = ""
    email = ""

end


fn create_user(name, email)

    User(
        name: name,
        email: email
    )

end

end
```

A module cannot contain runtime statements. Assigning an ordinary variable,
constructing a value for immediate use, printing, calling a function, or
branching must happen inside a function.

This is invalid:

```hmr
module Accounts

user = User(name: "Hirak")
print user.name

end
```

The interpreter reports:

```text
Hoomer Error:

Runtime statement found at module level.

Modules can only contain:
    import
    constant
    struct
    function

Move this code inside a function.
```

Runtime statements remain valid at the file's top level. There is no special
entry-point function: `hoomer run` evaluates the file from top to bottom.

```hmr
module Greeting

fn message()
    "Hello"
end

end

print Greeting.message()
```

---

# 6. Naming Convention

Naming is part of the language design.

The shape of a name should tell the reader what it represents.

## Modules

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

    name = ""
    email = ""
    active = true

end
```

Creating:

```hmr
user = User(
    name: "Hirak",
    email: "hirak@example.com"
)
```

Structs support:

- Default values
- Named fields
- Reflection

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
module Users

fn activate(user)

    user with {
        active: true
    }

end

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
DatabaseError(
    message: "Connection failed"
)
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

The symbol is a communication tool.

It tells the reader:

> This function may return an error value.

Example:

```hmr
user = save_user!(user)
```

The programmer can handle the result:

```hmr
when user as result

    User
        print result.name

    DatabaseError
        print result.message

end
```

The `!` is optional and does not change the function itself.

---

# 13. Predicate Functions

Functions ending with `?` represent questions.

They should return boolean values.

Example:

```hmr
fn active?(user)

    user.active

end
```

Usage:

```hmr
if user.active?

    print "Active"

end
```

The naming itself communicates intent.

---

# 14. Pattern Matching

Pattern matching is done using `when`.

Example:

```hmr
when result as response

    User

        print response.name


    DatabaseError

        print response.message


    nil

        print "Nothing found"


    _

        print "Unknown"

end
```

The `as` keyword creates a local name.

---

# 15. Why `as`

Hoomer avoids unnecessary variable creation.

Instead of:

```hmr
User user
```

Hoomer prefers:

```hmr
when result as user

    User
        print user.name

end
```

The binding is controlled by the `when` expression.

---

# 16. Functions

Functions are the main unit of behavior.

Example:

```hmr
fn greet(name)

    "Hello {name}"

end
```

The last expression is returned automatically.

Explicit return is available:

```hmr
fn validate(name)

    if name == ""

        return "Invalid"

    end

    "Valid"

end
```

---

# 17. Function Overloading

Functions can have multiple definitions based on arity.

Example:

```hmr
fn greet()

    "Hello"

end


fn greet(name)

    "Hello {name}"

end
```

The language supports function selection based on arguments.

---

# 18. Imports

Imports bring names from another module into the current scope.

Example:

```hmr
import Accounts.User
```

Import with custom name:

```hmr
import Accounts.Teacher as TeacherAccount
```

Import selected members:

```hmr
import Text:

    trim,
    lowercase
```

Imports are explicit.

---

# 19. Blocks

Blocks allow libraries to create readable APIs.

Example:

```hmr
Database.transaction do

    save_user(user)

end
```

A block is simply a function passed as an argument.

The language does not need special syntax for:

- Web frameworks
- Testing frameworks
- UI libraries
- Database libraries

Libraries build these.

---

# 20. Reflection

Hoomer supports runtime reflection.

Programs can inspect:

- Values
- Structs
- Modules
- Functions

Example:

```hmr
info = reflect(user)

print info.fields
```

Reflection enables:

- ORM libraries
- Serialization
- Frameworks
- Developer tools

---

# 21. Constants

Constants use UPPER_SNAKE_CASE.

Example:

```hmr
MAX_CONNECTIONS = 100
DEFAULT_TIMEOUT = 30
```

Constants are immutable.

---

# 22. State Philosophy

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

    value = 0

end
```

State is represented as data.

---

# 23. Language Goals

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

# 24. MVP Interpreter

The first implementation will be written in Python.

The MVP will include:

1. Lexer
2. Parser
3. AST
4. Interpreter
5. Runtime values
6. Modules
7. Structs
8. Functions
9. Pattern matching

The first goal is not performance.

The first goal is proving:

> Does Hoomer feel good to write?

---

# 25. Final Vision

Hoomer is built around a simple belief:

> The best programming language is the one that lets humans express ideas naturally.

A language should not make programmers think like machines.

The machine should work hard so humans can think clearly.
