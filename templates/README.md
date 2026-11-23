# 测评 JSON 输入模板

模板中的姓名与分数均为合成示例。替换为实际测评数据后，请同步更新
`assessment_metadata.data_source` 并移除 `synthetic` 标记。

推荐从 `assessment_input_example_26_metrics.json` 复制一份，为每位被试单独保存为
`.json` 文件，再修改以下内容：

1. `respondent_profile.report_subject_label`：报告中显示的脱敏姓名。
2. `grade` 和 `class_name`：年级、班级。
3. `assessment_metadata.source_student_id`：学生编号，例如填 `"1"`，报告中自动显示为
   “1号”；也可以直接填 `"1号"`，系统不会重复添加“号”。不要填写身份证件号码。
4. `scores`：将各指标的 `raw_score` 替换为第一张原始分数表中的数值。

只上传本次实际测得的指标即可；未测指标应删除对应键，不要填 `null`、空字符串或猜测值。
指标名称必须沿用模板中的标准名称，否则可能无法匹配常模、专业定义和图表模块。

控制台会根据页面中选择的小学版、初中版或高中版覆盖学段字段，因此模板中不需要填写
`school_stage` 或 `writing_variant`。

JSON 文件必须使用英文半角双引号，不能包含注释或末尾多余逗号。建议保存为 UTF-8。

`source_student_id` 只用于封面、首页和批量任务识别，不参与等级计算，也不会作为
心理画像或行为推断依据。为兼容旧数据，非纯数字的历史技术 ID 会保留在输入中但不显示。

注意：当前项目固定使用现有的 P20/P80 常模配置进行等级计算。正式区分不同学段常模前，
请由项目负责人确认所选报告版本与常模适用范围一致。
