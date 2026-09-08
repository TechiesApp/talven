"""Fixed offline tooling workloads and separate native acceptance drivers."""

from pathlib import Path

VERSION = "m1c-tooling-workloads-v1"
ROOT = Path(__file__).resolve().parents[1]


def chain_source(count: int) -> str:
    functions = ["fn step_0(value: i32) -> i32 {\n    return value + 1;\n}"]
    functions.extend(
        f"fn step_{i}(value: i32) -> i32 {{\n    return step_{i - 1}(value) + 1;\n}}"
        for i in range(1, count)
    )
    functions.append(
        f"fn main() -> i32 {{\n    if (step_{count - 1}(7) == {count + 7}) {{\n"
        "        return 0;\n    }\n    return 1;\n}"
    )
    return "\n\n".join(functions) + "\n"


def driver(declarations: str, checks: str) -> bytes:
    return ("#include <stdint.h>\n" + declarations + "\nextern int32_t tv_f_main(void);\n"
            "int main(void) {\n" + checks + "\nreturn tv_f_main() == 0 ? 0 : 1;\n}\n").encode()


def workloads() -> list[dict]:
    result = [
        {"id": "vectors", "origin": "examples/vectors.tal",
         "source": (ROOT / "examples/vectors.tal").read_bytes(),
         "oracle": driver(
             "struct tv_s_Vec2 { int32_t tv_m_x; int32_t tv_m_y; };\n"
             "extern int32_t tv_f_dot(struct tv_s_Vec2, struct tv_s_Vec2);",
             "if (tv_f_dot((struct tv_s_Vec2){2,3}, (struct tv_s_Vec2){4,5}) != 23) return 1;\n"
             "if (tv_f_dot((struct tv_s_Vec2){-3,4}, (struct tv_s_Vec2){5,-2}) != -23) return 1;\n"
             "if (tv_f_dot((struct tv_s_Vec2){0,0}, (struct tv_s_Vec2){9,-7}) != 0) return 1;\n"
             "if (tv_f_dot((struct tv_s_Vec2){1000,2000}, (struct tv_s_Vec2){3000,4000}) != 11000000) return 1;"),
         "criteria": "Four full-i32 dot products (positive, negative, zero, large); main returns zero."},
        {"id": "borrowing", "origin": "examples/borrowing.tal",
         "source": (ROOT / "examples/borrowing.tal").read_bytes(),
         "oracle": driver(
             "struct tv_s_Counter { int32_t tv_m_value; };\n"
             "extern int32_t tv_f_read(const struct tv_s_Counter *);\n"
             "extern int32_t tv_f_add(struct tv_s_Counter *, int32_t);\n"
             "extern int32_t tv_f_step_twice(struct tv_s_Counter *);",
             "const int32_t starts[] = {-1000, -2, 0, 40, 1000000};\n"
             "for (unsigned i = 0; i < sizeof(starts)/sizeof(starts[0]); ++i) {\n"
             "struct tv_s_Counter c = {starts[i]};\n"
             "if (tv_f_read(&c) != starts[i] || c.tv_m_value != starts[i]) return 1;\n"
             "if (tv_f_add(&c, -3) != starts[i]-3 || c.tv_m_value != starts[i]-3) return 1;\n"
             "if (tv_f_step_twice(&c) != starts[i]-1 || c.tv_m_value != starts[i]-1) return 1;\n} "),
         "criteria": "Five initial values; read preserves owner, add/step_twice return and mutate correctly; main returns zero."},
    ]
    for count in (32, 128):
        result.append({
            "id": f"chain-{count}", "origin": f"generated: {count} helpers plus main",
            "source": chain_source(count).encode(),
            "oracle": driver(f"extern int32_t tv_f_step_{count - 1}(int32_t);",
                             f"if (tv_f_step_{count - 1}(-1000) != {count - 1000}) return 1;\n"
                             f"if (tv_f_step_{count - 1}(0) != {count}) return 1;\n"
                             f"if (tv_f_step_{count - 1}(1000000) != {count + 1000000}) return 1;"),
            "criteria": f"{count}-helper chain returns input + {count} for three full-i32 inputs; main returns zero.",
        })
    return result


CANDIDATE_SUFFIX = b"\nfn baseline_added() -> i32 {\n    return 0;\n}\n"
