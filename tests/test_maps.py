from __future__ import annotations

import unittest

from hoomer.errors import RuntimeHoomerError
from tests.helpers import run_hoomer


class MapTests(unittest.TestCase):
    def test_map_literals_support_lookup_assignment_and_missing_keys(self) -> None:
        _, output, _ = run_hoomer(
            '''field_name = "email"
user = {
    "name": "Hirak",
    field_name: "hirak@example.com",
}

print(user["name"])
print(user["email"])
print(user["city"])

user["city"] = "Guwahati"
print(user["city"])
'''
        )

        self.assertEqual(
            output,
            "Hirak\nhirak@example.com\nnil\nGuwahati\n",
        )

    def test_map_membership_tests_keys(self) -> None:
        _, output, _ = run_hoomer(
            '''values = {"present": nil}

print("present" in values)
print("missing" in values)
'''
        )

        self.assertEqual(output, "true\nfalse\n")

    def test_map_equality_is_structural_and_ignores_insertion_order(self) -> None:
        _, output, _ = run_hoomer(
            '''first = {
    "name": "Hirak",
    "roles": ["admin", "editor"],
}

second = {
    "roles": ["admin", "editor"],
    "name": "Hirak",
}

different = {
    "name": "Rahul",
    "roles": ["admin", "editor"],
}

print(first == second)
print(first != different)
print(first)
'''
        )

        self.assertEqual(
            output,
            'true\ntrue\n{"name": "Hirak", "roles": ["admin", "editor"]}\n',
        )

    def test_map_iteration_preserves_insertion_order(self) -> None:
        _, output, _ = run_hoomer(
            '''scores = {
    "Hirak": 10,
    "Rahul": 20,
}

for name, score in scores
    print("{name}: {score}")
end

for name in scores
    print(name)
end
'''
        )

        self.assertEqual(output, "Hirak: 10\nRahul: 20\nHirak\nRahul\n")

    def test_map_keys_must_be_stable_scalar_values(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer('invalid = {["mutable"]: true}\n')

        rendered_error = str(caught_error.exception)
        self.assertIn("cannot be used as a map key", rendered_error)
        self.assertIn("string, number, boolean, or nil", rendered_error)

    def test_two_loop_variables_are_reserved_for_maps(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer(
                '''for index, value in ["first", "second"]
    print(value)
end
'''
            )

        self.assertIn("Only a map loop", str(caught_error.exception))

    def test_package_constant_can_contain_an_inert_map(self) -> None:
        _, output, _ = run_hoomer(
            '''package Configuration

DEFAULTS = {
    "host": "localhost",
    "port": 8080,
}

fn main
    print(DEFAULTS["host"])
end
'''
        )

        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
