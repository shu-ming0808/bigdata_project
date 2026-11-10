-- 教師推薦證據：只保留正常開課、確定由一位教師授課的班次。
-- 這是檢視表；原始開課列不刪除，學生修課分析也不受影響。
CREATE VIEW solo_teacher_offering_evidence AS
SELECT
    o.offering_id,
    o.term_code,
    o.course_serial_no,
    o.course_code,
    o.course_name,
    o.department_code,
    o.department_name,
    o.teaching_language_raw,
    TRIM(r.instructors) AS instructor_name
FROM course_offerings AS o
JOIN course_offering_raw AS r
  ON r.offering_row_id = o.offering_id
WHERE o.offering_status_raw = '正常'
  AND TRIM(r.instructor_count) = '1'
  AND NULLIF(TRIM(r.instructors), '') IS NOT NULL;
