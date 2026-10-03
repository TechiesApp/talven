//! Provenance and release obligations for the explicit supplied-block profile.
use super::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Slot {
    Free,
    Pending,
    Live,
}
const BUILTINS: [&str; 8] = [
    "Block",
    "Allocation",
    "ByteRead",
    "ByteWrite",
    "reserve",
    "release",
    "read_byte",
    "write_byte",
];
fn token(name: &str) -> Token {
    Token {
        kind: TokenKind::Id,
        text: name.into(),
        span: 0..0,
    }
}
pub(super) fn declarations(
    records: &mut Vec<Record>,
    functions: &[Function],
) -> Result<BTreeMap<String, usize>> {
    let mut names: BTreeSet<&str> = ["i32", "bool", "str", "print"].into();
    names.extend(BUILTINS);
    for name in records
        .iter()
        .map(|r| &r.name)
        .chain(functions.iter().map(|f| &f.name))
    {
        if !names.insert(&name.text) {
            return Err(error(
                "E0102",
                format!("Duplicate or reserved declaration {}", name.text),
                name.span.clone(),
            ));
        }
    }
    let mut builtins = vec![Record {
        name: token("Block"),
        fields: Vec::new(),
        resolved: Vec::new(),
        variants: None,
        opaque: true,
    }];
    for (name, variants) in [
        (
            "Allocation",
            vec![
                ("Granted", Some("Block")),
                ("InvalidRequest", None),
                ("Exhausted", None),
            ],
        ),
        (
            "ByteRead",
            vec![("Value", Some("i32")), ("OutOfBounds", None)],
        ),
        (
            "ByteWrite",
            vec![
                ("Written", None),
                ("OutOfBounds", None),
                ("InvalidByte", None),
            ],
        ),
    ] {
        builtins.push(Record {
            name: token(name),
            fields: Vec::new(),
            resolved: Vec::new(),
            variants: Some(
                variants
                    .into_iter()
                    .map(|(name, ty)| (token(name), ty.map(token)))
                    .collect(),
            ),
            opaque: false,
        });
    }
    builtins.append(records);
    *records = builtins;
    check_declarations_profiles(records, functions, true)
}
pub(super) fn signature_shape(function: &Function) -> Result<()> {
    if matches!(base_type(&function.result.text), "Block" | "Allocation") {
        return Err(error(
            "E0320",
            "Resource owners and regions cannot escape through function results",
            function.result.span.clone(),
        ));
    }
    for (_, ty) in &function.params {
        if matches!(
            ty.text.as_str(),
            "Allocation" | "&Allocation" | "&mut Allocation"
        ) {
            return Err(error(
                "E0320",
                "Allocation and regions cannot be function parameters",
                ty.span.clone(),
            ));
        }
    }
    Ok(())
}
fn base_type(text: &str) -> &str {
    text.strip_prefix("&mut ")
        .or_else(|| text.strip_prefix('&'))
        .unwrap_or(text)
}
pub(super) fn function_bounds(function: &Function) -> Result<()> {
    let mut pending: Vec<&Stmt> = function.body.iter().rev().collect();
    let mut count = 0;
    while let Some(stmt) = pending.pop() {
        if stmt.kind == StmtKind::Region {
            count += 1;
            let capacity = stmt.capacity.as_ref().unwrap();
            if !capacity
                .text
                .parse::<usize>()
                .is_ok_and(|n| (1..=4096).contains(&n))
            {
                return Err(error(
                    "E0320",
                    "Region capacity must be 1..4096 bytes",
                    capacity.span.clone(),
                ));
            }
            if count > 8 {
                return Err(error(
                    "E0320",
                    "At most eight regions are allowed per function",
                    stmt.name.as_ref().unwrap().span.clone(),
                ));
            }
        }
        let children: Vec<_> = stmt
            .then
            .iter()
            .chain(&stmt.otherwise)
            .chain(stmt.arms.iter().flat_map(|a| a.body.iter()))
            .collect();
        pending.extend(children.into_iter().rev());
    }
    Ok(())
}
impl Checker<'_> {
    pub(super) fn is_resource(&self, ty: Ty, name: &str) -> bool {
        matches!(ty, Ty::Record(i) if self.records[i].name.text == name && self.resources)
    }
    pub(super) fn resource_binding_exit(&self, name: &str, state: &State) -> Result<()> {
        if !state.moved.contains(name)
            && state.bindings.get(name).is_some_and(|ty| {
                self.is_resource(*ty, "Block") || self.is_resource(*ty, "Allocation")
            })
        {
            return Err(error(
                "E0321",
                format!("Resource {name} leaves scope unreleased"),
                state.declarations[name].clone(),
            ));
        }
        Ok(())
    }
    pub(super) fn resource_return(&self, state: &State, span: Range<usize>) -> Result<()> {
        if state.origins.values().any(|s| *s != Slot::Free) {
            return Err(error(
                "E0321",
                "Normal return requires every resource obligation to be released",
                span,
            ));
        }
        Ok(())
    }
    pub(super) fn resource_join(
        &self,
        state: &mut State,
        survivors: &[State],
        span: Range<usize>,
    ) -> Result<()> {
        let Some(first) = survivors.first() else {
            return Ok(());
        };
        for origin in state.origins.keys() {
            if survivors
                .iter()
                .any(|branch| branch.origins.get(origin) != first.origins.get(origin))
            {
                return Err(error(
                    "E0321",
                    "Resource obligations must agree on continuing branches",
                    span,
                ));
            }
        }
        for name in state.binding_origins.keys() {
            if survivors
                .iter()
                .any(|s| s.moved.contains(name) != first.moved.contains(name))
            {
                return Err(error(
                    "E0321",
                    format!("Resource {name} must be consumed consistently on continuing branches"),
                    span,
                ));
            }
        }
        for (origin, slot) in &mut state.origins {
            *slot = first.origins[origin];
        }
        Ok(())
    }
    pub(super) fn resource_region(&mut self, stmt: &Stmt, state: &mut State) -> Result<bool> {
        let name = stmt.name.as_ref().unwrap();
        if state.regions.contains_key(&name.text) || state.bindings.contains_key(&name.text) {
            return Err(error(
                "E0102",
                format!("Duplicate or shadowed binding {}", name.text),
                name.span.clone(),
            ));
        }
        let origin = name.span.start;
        let old_bindings: BTreeSet<_> = state.bindings.keys().cloned().collect();
        state.regions.insert(name.text.clone(), origin);
        state.origins.insert(origin, Slot::Free);
        let continuing = self.block(&stmt.then, state)?;
        if continuing && state.origins[&origin] != Slot::Free {
            return Err(error(
                "E0321",
                "Region leaves scope with an outstanding owner or reservation",
                name.span.clone(),
            ));
        }
        state.regions.remove(&name.text);
        state.origins.remove(&origin);
        state.bindings.retain(|n, _| old_bindings.contains(n));
        state.declarations.retain(|n, _| old_bindings.contains(n));
        state
            .binding_origins
            .retain(|n, _| old_bindings.contains(n));
        state.mutable.retain(|n| old_bindings.contains(n));
        state.moved.retain(|n| old_bindings.contains(n));
        Ok(continuing)
    }
    pub(super) fn resource_call(
        &mut self,
        index: usize,
        name: &str,
        args: &[usize],
        state: &mut State,
    ) -> Result<Ty> {
        let span = self.expressions[index].span.clone();
        let expected_count = match name {
            "reserve" | "write_byte" => 3,
            "read_byte" => 2,
            _ => 1,
        };
        if args.len() != expected_count {
            return Err(error(
                "E0203",
                format!("{name} expects {expected_count} arguments"),
                span,
            ));
        }
        if name == "reserve" {
            let first = &self.expressions[args[0]];
            let origin = match &first.kind {
                ExprKind::Name(name) => state.regions.get(name).copied(),
                _ => None,
            }
            .ok_or_else(|| {
                error(
                    "E0320",
                    "reserve requires a lexical region name as its first argument",
                    first.span.clone(),
                )
            })?;
            if state.origins[&origin] != Slot::Free {
                return Err(error(
                    "E0321",
                    "Region already has an outstanding owner or reservation",
                    first.span.clone(),
                ));
            }
            let outer_loans = state.loans.clone();
            let checked = (|| {
                for arg in &args[1..] {
                    let actual = self.argument(*arg, state)?;
                    self.same(actual, Ty::Int, self.expressions[*arg].span.clone())?;
                }
                Ok(())
            })();
            state.loans = outer_loans;
            checked?;
            state.origins.insert(origin, Slot::Pending);
            self.expression_origins.insert(index, origin);
            return Ok(Ty::Record(self.record_index["Allocation"]));
        }
        let outer_loans = state.loans.clone();
        let checked = (|| {
            let expected = if name == "release" {
                Ty::Record(self.record_index["Block"])
            } else {
                Ty::Borrowed(self.record_index["Block"], name == "write_byte")
            };
            let actual = if matches!(self.expressions[args[0]].kind, ExprKind::Borrow(..)) {
                self.borrow(args[0], state)?
            } else if matches!(expected, Ty::Borrowed(..)) {
                return Err(error(
                    "E0304",
                    format!(
                        "Pass {} explicitly with &name or &mut name",
                        expected.name(self.records)
                    ),
                    self.expressions[args[0]].span.clone(),
                ));
            } else {
                self.expr(args[0], state, true)?
            };
            self.same(actual, expected, self.expressions[args[0]].span.clone())?;
            for arg in &args[1..] {
                let actual = self.argument(*arg, state)?;
                self.same(actual, Ty::Int, self.expressions[*arg].span.clone())?;
            }
            if name == "release" {
                let origin = self.expression_origins[&args[0]];
                state.origins.insert(origin, Slot::Free);
            }
            Ok(())
        })();
        state.loans = outer_loans;
        checked?;
        Ok(match name {
            "release" => Ty::Int,
            "read_byte" => Ty::Record(self.record_index["ByteRead"]),
            _ => Ty::Record(self.record_index["ByteWrite"]),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const MATCH: &str = "Allocation::Granted(b) { release(b); } Allocation::InvalidRequest {} Allocation::Exhausted {}";
    fn region(body: &str) -> String {
        format!("fn main() -> i32 {{ region r(64) {{ {body} }} return 0; }}")
    }
    fn failure(source: &str) -> Error {
        analyze_resources(source).unwrap_err()
    }

    #[test]
    fn moves_rewrap_and_delegation_keep_one_origin() {
        let source = "fn consume(b:Block)->i32 { let moved=b; let a=Allocation::Granted(moved); match(a){ Allocation::Granted(owner){ return release(owner); } Allocation::InvalidRequest{return 1;} Allocation::Exhausted{return 2;} } } fn main()->i32{ region r(64){ let a=reserve(r,8,8); match(a){ Allocation::Granted(block){return consume(block);} Allocation::InvalidRequest{return 3;} Allocation::Exhausted{return 4;} } } }";
        let program = analyze_resources(source).unwrap();
        let c = emit_c(&program, false).unwrap();
        assert!(c.contains("tv_block tv_v_moved = tv_tmp_1;"));
        assert!(c.contains("tv_source_init(&tv_region_r, tv_storage_r, 64);"));
        assert!(c.contains(include_str!("../../supplied-storage/runtime.h")));
        assert!(c.contains(include_str!("../../supplied-storage/source-runtime.c")));
        assert!(!c.contains("struct tv_s_Block"));
    }

    #[test]
    fn pending_and_match_payload_obligations_are_checked() {
        assert_eq!(
            failure(&region("let a=reserve(r,1,1);")).message,
            "Resource a leaves scope unreleased"
        );
        let source = region(
            "match(reserve(r,1,1)){Allocation::Granted(b){} Allocation::InvalidRequest{} Allocation::Exhausted{}}",
        );
        assert_eq!(
            failure(&source).message,
            "Resource b leaves scope unreleased"
        );
        let source = region("let a=reserve(r,1,1); let second=reserve(r,1,1);");
        assert_eq!(
            failure(&source).message,
            "Region already has an outstanding owner or reservation"
        );
        assert_eq!(
            failure("fn f(b:Block)->i32 {let moved=b; return 0;}").message,
            "Resource moved leaves scope unreleased"
        );
        assert_eq!(
            failure("fn f(b:Block)->i32 {b; return 0;}").message,
            "Resource owner or reservation cannot be discarded"
        );
    }

    #[test]
    fn optional_and_continuing_paths_must_agree() {
        let source = "fn f(b:Block,c:bool)->i32{ if(c){release(b);} return 0;}";
        assert_eq!(
            failure(source).message,
            "Resource obligations must agree on continuing branches"
        );
        let source = "fn free(b:Block)->bool{release(b);return true;} fn f(b:Block)->i32{let result=true && free(b);return 0;}";
        assert_eq!(failure(source).code, "E0321");
        assert!(
            analyze_resources(
                "fn f(b:Block,c:bool)->i32{if(c){return release(b);} release(b);return 0;}"
            )
            .is_ok()
        );
        assert!(
            analyze_resources(
                "fn f(b:Block,c:bool)->i32{if(c){release(b);}else{release(b);}return 0;}"
            )
            .is_ok()
        );
    }

    #[test]
    fn opaque_types_and_loan_rules_preserve_normal_diagnostics() {
        for source in [
            "fn f()->Block{return 0;}",
            "fn f(a:Allocation)->i32{return 0;}",
            "struct Box{x:Block}",
            "outcome Box{Child(Allocation)}",
            "fn f()->i32{let b=Block{};return 0;}",
            "fn f()->i32{let a=Allocation::Exhausted;return 0;}",
            "fn f(b:Block)->i32{return b.length;}",
        ] {
            assert_eq!(failure(source).code, "E0320", "{source}");
        }
        assert_eq!(
            failure("fn f(b:Block)->i32{release(b);release(b);return 0;}").code,
            "E0301"
        );
        assert_eq!(
            failure("fn f(b:Block)->i32{read_byte(&b,release(b));return 0;}").code,
            "E0302"
        );
        assert_eq!(
            failure("fn f(b:&Block)->i32{return release(b);}").code,
            "E0304"
        );
        assert_eq!(
            failure("fn f(b:Block)->i32{write_byte(&mut b,0,1);release(b);return 0;}").code,
            "E0303"
        );
        assert_eq!(
            failure("fn f(b:Block)->i32{read_byte(&b,0);release(b);return 0;}").code,
            "E0311"
        );
        assert_eq!(failure("fn f(b:Block)->i32{return false;}").code, "E0201");
    }

    #[test]
    fn regions_remain_lexical_and_bounded() {
        assert_eq!(failure(&region("let value=r;")).code, "E0320");
        assert!(analyze_resources(&region(&format!("let a=reserve(r,1,1);match(a){{{MATCH}}} let again=reserve(r,0,3);match(again){{{MATCH}}}"))).is_ok());
        assert_eq!(
            failure("fn f()->i32{region r(0){} return 0;}").code,
            "E0320"
        );
        assert_eq!(
            failure("fn f()->i32{region r(4097){} return 0;}").code,
            "E0320"
        );
        let source = format!(
            "fn f()->i32{{{}return 0;}}",
            (0..9)
                .map(|i| format!("region r{i}(1){{}}"))
                .collect::<String>()
        );
        assert_eq!(
            failure(&source).message,
            "At most eight regions are allowed per function"
        );
        let source = "fn f()->i32{region r(1){let x=1;} region r(1){let x=2;} return 0;}";
        assert!(analyze_resources(source).is_ok());
    }

    #[test]
    fn resource_syntax_keeps_existing_tree_and_parse_limits() {
        let shallow = format!(
            "fn f()->i32{{{}region r(1){{}}{}return 0;}}",
            "if(true){".repeat(126),
            "}".repeat(126)
        );
        assert!(format_resources(&shallow).is_ok());
        let deep = format!(
            "fn f()->i32{{{}region r(1){{}}{}return 0;}}",
            "if(true){".repeat(127),
            "}".repeat(127)
        );
        assert_eq!(format_resources(&deep).unwrap_err().code, "E0005");
        let parentheses = format!(
            "fn f()->i32{{return {}0{};}}",
            "(".repeat(255),
            ")".repeat(255)
        );
        assert_eq!(analyze_resources(&parentheses).unwrap_err().code, "E0005");
    }

    #[test]
    fn leading_zero_capacity_has_no_smaller_lexical_limit() {
        let source = format!(
            "fn main()->i32{{region r({}1){{}}return 0;}}",
            "0".repeat(5000)
        );
        let program = analyze_resources(&source).unwrap();
        assert!(
            emit_c(&program, false)
                .unwrap()
                .contains("_Alignas(16) uint8_t tv_storage_r[1];")
        );
        let formatted = format_resources(&source).unwrap();
        assert!(formatted.contains(&format!("region r({}1)", "0".repeat(5000))));
        assert_eq!(format_resources(&formatted).unwrap(), formatted);
    }

    #[test]
    fn base_names_and_resource_formatter_stay_isolated() {
        let source = "struct Block{x:i32} struct Allocation{x:i32} fn reserve()->i32{return 0;} fn release()->i32{return 0;}";
        assert!(analyze(source).is_ok());
        assert!(analyze_outcomes(source).is_ok());
        assert_eq!(failure(source).code, "E0102");
        assert!(
            analyze_resources("struct Region{x:i32} fn f(r:Region)->Region{return r;}").is_ok()
        );
        let source = region(&format!("let a=reserve(r,1,1);match(a){{{MATCH}}}"));
        let formatted = format_resources(&source).unwrap();
        assert_eq!(format_resources(&formatted).unwrap(), formatted);
        assert!(analyze_resources(&formatted).is_ok());
        assert!(format_source(&source).is_err());
    }
}
