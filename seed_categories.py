"""Legacy category seed disabled by 10D-A.

The old financial category taxonomy, CategoryRule mappings and automatic
"Outros" fallback are no longer allowed to be created. This script is kept as
a no-op only so old operational notes fail safely instead of recreating legacy
data.
"""


def main() -> None:
    print(
        "10D-A: legacy category seeding is disabled; no categories or category rules were created."
    )


if __name__ == "__main__":
    main()
