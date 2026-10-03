# Module profile reference for agents

This is the implemented companion profile `m1-local-modules-v1`. Read the
[core language reference](language-reference.md) for expressions, strict types,
ownership, explicit call-scoped borrowing and checked arithmetic. This companion
adds source modules; it does not add heap allocation, loops or escaping references.

An explicit source bundle has one entry file and root-relative module paths.
Leading imports select public declarations:

```talven
import "ledger.tal" { Account as Ledger, debit as apply };

fn update(value: i32) -> i32 {
    let mut account = Ledger { balance: value };
    return apply(&mut account, 2);
}
```

The dependency might contain:

```talven
pub struct Account { balance: i32 }

pub fn debit(a: &mut Account, delta: i32) -> i32 {
    a.balance = a.balance - delta;
    return a.balance;
}
```

Declarations are private unless prefixed with `pub`. An import selects declarations
owned directly by its target module; there are no wildcards, reexports, cycles or
implicit transitive names. Optional `as` aliases are local source names. A path is
relative to the bundle root, including imports in nested files.

Each record has nominal identity in its defining module. Two modules declaring
`Account { balance: i32 }` define different types. An alias preserves identity.
Build an explicitly named record from scalar field values to convert between
equally shaped types. Inferred results can carry a public record type without an
imported type name; naming or constructing that type requires importing its name.

Records remain move-only; scalar fields copy. A borrowed record cannot be moved
into a by-value parameter. Call borrows explicitly: `read(&owner)` and
`write(&mut owner)`, including explicit reborrowing of borrowed parameters.
Borrows last through their call expression. An owned temporary record can be
passed by value; a shared or exclusive borrow requires an appropriate place.

Compiler context uses qualified identities such as `ledger.tal::Account` and
`ledger.tal::debit`. These are receipt labels, **not source syntax**. Use the local
import aliases in code. Internal flattened compiler identifiers are reserved.
Private dependency functions are visible in read-only source but unavailable to
the importing file. Public function signatures cannot expose a private own type.

The loader checks only the reachable graph: at most 32 modules, 16 import levels,
256 KiB original UTF-8 and 16,384 tokens; shared core limits also apply to flattened
source. Paths use ASCII letters, digits, underscores or hyphens and `/` separators,
end in `.tal`, and contain no dot segments, absolute paths or symlinks.

For the complete tool contract and remaining limitations, see [local modules](modules.md).
