from __future__ import annotations

import unittest

from tests.helpers import run_hoomer


class StructMatchingReflectionTests(unittest.TestCase):
    def test_struct_defaults_named_construction_field_access_and_assignment(self) -> None:
        _, output, _ = run_hoomer(
            """struct User
    name = "Unknown"
    age = 0
end

user = User(age: 26)
print user.name
user.name = "Hirak"
print user.name
"""
        )

        self.assertEqual(output, "Unknown\nHirak\n")


    def test_when_matches_struct_nil_and_wildcard_top_to_bottom(self) -> None:
        _, output, _ = run_hoomer(
            """struct User
    name = ""
end

fn describe(value)
    when value as result
        User
            "User: {result.name}"
        nil
            "No value"
        _
            "Unknown value"
    end
end

print describe(User(name: "Hirak"))
print describe(nil)
print describe(42)
"""
        )

        self.assertEqual(output, "User: Hirak\nNo value\nUnknown value\n")


    def test_error_structs_are_ordinary_values_matched_by_type(self) -> None:
        _, output, _ = run_hoomer(
            """struct DatabaseError
    message
end

result = DatabaseError(message: "Connection failed")

when result as response
    DatabaseError
        print response.message
    _
        print "Unexpected"
end
"""
        )

        self.assertEqual(output, "Connection failed\n")


    def test_reflection_exposes_struct_and_function_information(self) -> None:
        _, output, _ = run_hoomer(
            """struct User
    name = ""
    age = 0
end

fn greet(user)
    "Hello {user.name}"
end

user_info = reflect(User(name: "Hirak"))
function_info = reflect(greet)
print user_info.name
print user_info.fields
print function_info.name
print function_info.parameters
"""
        )

        self.assertEqual(output, "User\n['name', 'age']\ngreet\n['user']\n")
