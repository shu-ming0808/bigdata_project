"""Create additive, auditable MySQL views shared by the student and teacher projects.

No raw table is changed. Run with the configured local MySQL login path.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from english_taught_analysis import DEFAULT_MYSQL, HERE, frame


COURSE_VIEW = "shared_1150012_course_v"
TEACHER_VIEW = "shared_1150012_solo_teacher_v"


def execute(mysql: Path, login_path: str, database: str, sql: str) -> None:
    result = subprocess.run(
        [str(mysql), f"--login-path={login_path}", "--default-character-set=utf8mb4",
         "--batch", "--raw", database],
        input=sql.encode("utf-8"), capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))


def scalar(args: argparse.Namespace, sql: str) -> int:
    return int(frame(args.mysql, args.login_path, args.database, sql).iloc[0, 0])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--output-dir", type=Path, default=HERE / "outputs" / "shared_layer")
    args = parser.parse_args()

    if scalar(args, "SELECT COUNT(*) FROM course_offerings") != 46893:
        raise RuntimeError("course_offerings row count changed; inspect source before rebuilding views")
    if scalar(args, "SELECT COUNT(*) FROM enrollment_records") != 1403645:
        raise RuntimeError("enrollment_records row count changed; inspect source before rebuilding views")
    existing = frame(args.mysql, args.login_path, args.database, """
        SELECT table_name, table_type FROM information_schema.tables
        WHERE table_schema=DATABASE()
          AND table_name IN ('shared_1150012_course_v','shared_1150012_solo_teacher_v')
    """)
    if not existing.empty and any(existing.iloc[:, 1].ne("VIEW")):
        raise RuntimeError("Shared layer name belongs to a table; refusing to replace it")

    course_sql = f"""
    CREATE OR REPLACE VIEW {COURSE_VIEW} AS
    SELECT o.offering_id, o.term_code, o.course_serial_no,
           NULLIF(TRIM(o.course_code),'') AS course_code,
           NULLIF(TRIM(o.course_name),'') AS course_name,
           NULLIF(TRIM(o.department_code),'') AS department_code,
           NULLIF(TRIM(o.department_name),'') AS department_name,
           NULLIF(TRIM(o.offering_class),'') AS offering_class,
           NULLIF(TRIM(o.course_attribute_raw),'') AS course_attribute,
           NULLIF(TRIM(o.teaching_language_raw),'') AS teaching_language,
           CASE WHEN TRIM(o.teaching_language_raw)='英語' THEN 'english'
                WHEN TRIM(o.teaching_language_raw)='部份英語' THEN 'partial_english'
                ELSE 'other' END AS language_group,
           CASE WHEN TRIM(o.emi_raw)='是' THEN 'yes'
                WHEN TRIM(o.emi_raw)='否' THEN 'no'
                ELSE 'unknown' END AS formal_emi_status,
           NULLIF(TRIM(o.offering_status_raw),'') AS offering_status,
           CASE WHEN TRIM(o.offering_status_raw)='正常' THEN 1 ELSE 0 END AS is_open,
           CASE WHEN o.course_code LIKE 'LN%'
                  OR o.course_name REGEXP '大一英文|進修英文|TOEIC|英文能力鑑定|英語能力鑑定'
                  OR l.english_level IN ('beginner','intermediate','advanced')
                THEN 1 ELSE 0 END AS is_language_learning_course,
           NULLIF(TRIM(r.instructors),'') AS instructors_raw,
           NULLIF(TRIM(r.instructor_count),'') AS instructor_count_raw,
           NULLIF(TRIM(r.offering_grade_level),'') AS offering_grade_level,
           NULLIF(TRIM(r.degree_level_name),'') AS degree_level,
           NULLIF(TRIM(r.teaching_method_lecture),'') AS lecture_method_raw,
           NULLIF(TRIM(r.teaching_method_practicum_lab),'') AS practicum_method_raw
    FROM course_offerings o
    JOIN course_offering_raw r ON r.offering_row_id=o.offering_id
    LEFT JOIN offering_english_level l ON l.offering_id=o.offering_id
    """
    teacher_sql = f"""
    CREATE OR REPLACE VIEW {TEACHER_VIEW} AS
    SELECT c.offering_id,c.term_code,c.course_serial_no,c.course_code,c.course_name,
           c.department_code,c.department_name,c.course_attribute,c.degree_level,
           c.teaching_language,c.language_group,
           c.formal_emi_status,c.offering_status,c.is_language_learning_course,
           c.instructors_raw AS instructor_name,
           'name_only_unverified' AS instructor_identity_quality
    FROM {COURSE_VIEW} c
    WHERE c.is_open=1 AND c.instructor_count_raw='1'
      AND c.instructors_raw IS NOT NULL
    """
    execute(args.mysql, args.login_path, args.database, course_sql)
    execute(args.mysql, args.login_path, args.database, teacher_sql)

    quality = frame(args.mysql, args.login_path, args.database, f"""
        SELECT c.term_code, COUNT(*) offering_count,
               SUM(c.is_open=1) open_offerings,
               SUM(c.language_group='english') english_offerings,
               SUM(c.language_group='partial_english') partial_english_offerings,
               SUM(c.formal_emi_status='yes') formal_emi_yes,
               SUM(c.formal_emi_status='unknown') formal_emi_unknown,
               SUM(c.course_code IS NULL) missing_course_code,
               SUM(c.department_code IS NULL) missing_department_code,
               SUM(c.instructor_count_raw='1' AND c.instructors_raw IS NOT NULL) solo_teacher_rows,
               SUM(COALESCE(c.instructor_count_raw,'') NOT IN ('','1')) non_solo_teacher_rows
        FROM {COURSE_VIEW} c GROUP BY c.term_code ORDER BY c.term_code
    """)
    key_checks = {
        "source_offerings": scalar(args, "SELECT COUNT(*) FROM course_offering_raw"),
        "unique_linked_offerings": scalar(args, f"SELECT COUNT(*) FROM {COURSE_VIEW}"),
        "duplicate_term_serial_keys": scalar(args, """
            SELECT COUNT(*) FROM (SELECT term_code,course_serial_no FROM course_offerings
            GROUP BY term_code,course_serial_no HAVING COUNT(*)>1) x"""),
        "enrollment_rows": scalar(args, "SELECT COUNT(*) FROM enrollment_records"),
        "linked_enrollment_rows": scalar(args, "SELECT COUNT(*) FROM enrollment_records WHERE offering_id IS NOT NULL"),
        "solo_teacher_evidence_rows": scalar(args, f"SELECT COUNT(*) FROM {TEACHER_VIEW}"),
        "course_offering_fk_misses": scalar(args, """
            SELECT COUNT(*) FROM enrollment_records e LEFT JOIN course_offerings o
              ON o.offering_id=e.offering_id
            WHERE e.offering_id IS NOT NULL AND o.offering_id IS NULL"""),
    }
    if key_checks["duplicate_term_serial_keys"] or key_checks["course_offering_fk_misses"]:
        raise RuntimeError(f"Shared key quality check failed: {key_checks}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    quality.to_csv(args.output_dir / "course_quality_by_term.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "key_quality.json").write_text(
        json.dumps(key_checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(key_checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
