# Expert Definition And Parent Translation Method

## Purpose

Detailed analysis is not a collection of score comments. For each measured indicator, write a short expert-style explanation that helps a parent understand three things in order:

1. What psychological or educational construct the indicator observes.
2. What kind of task or daily behavior that construct is related to.
3. What the current class-referenced result may mean for this child, without inventing an event or treating a score as a diagnosis.

The expert report corpus is a source of phrasing, structure, and conceptual vocabulary. It is not a source of factual claims about a new child.

## Runtime Definition Source

For the 26 current indicators, the fixed professional explanation is the first
complete sentence for that indicator in the source workbook's `维度详解` sheet.
The extracted, auditable copy is `excel_dimension_detail_definitions.json`.

- Write that sentence into the detailed indicator block exactly; do not ask the
  model to paraphrase it or replace it with “观察……的倾向”.
- Do not copy the later sentences from the workbook. They are legacy examples
  and may contain exaggerated wording, assumed life experiences, or fixed-trait
  claims that are not evidence about a new child.
- The child-specific part begins only after the fixed definition: first state
  the input-calibrated level, then explain how that level is likely to appear
  in a relevant task or interaction. Concrete parent actions belong in the
  separate growth-support pages, not at the end of every indicator block.

## Visible Three-Part Structure

Use this order inside every `【指标名】` block. The finished block should normally be two to four connected sentences, not separately labelled bullets.

1. **Construct name**: write a concise professional subtitle after the heading.
2. **Accurate definition**: state what process is being observed and, where appropriate, its developmental function.
3. **Child-specific result analysis**: calibrate the wording to the supplied score and level, then explain the likely task performance in a school, task, play, or home situation. The first two sentences should describe the child-facing meaning of the result; do not turn every block into “家长可留意/家长可观察”.

Use connectors in rotation: “在……任务中”“面对……时”“当要求提高时”“这项表现提示”。 Do not repeat “本次结果提示” in every block. Keep direct parent instructions for `parent_suggestions` unless one brief observation cue is genuinely necessary.

## Internal Measurement Boundary

Keep the following rule during drafting and checking; do **not** mechanically write it into every indicator block: a task score reflects a current tendency, not a fixed personality, brain diagnosis, family cause, or life history. Put the general scope statement once in the report's `boundary_note` when needed. Only mention a measurement limitation in a detailed block when the specific wording would otherwise be misleading.

## Professional Language Standard

- A professional definition should name the construct and its function, not merely repeat the indicator name.
- Cognitive terms such as “执行控制”“持续性注意”“发散思维”“规则抽象”“自我效能感” are appropriate only when the next clause explains them in ordinary language.
- Brain-related wording is allowed only as a general developmental context: “与前额叶相关的执行控制过程有关”。 Never write that a single score proves a brain region is mature, impaired, or abnormal.
- Do not use “决定”“证明”“天生”“毫不费力”“极其”“完全”等超出一次测评证据的词。

## Construct Families

### Attention And Executive Control

Use for 注意稳定性、整体执行功能、抑制控制(Nogo)、抑制控制(go)、认知灵活性、学习速度。

- **Attention stability / sustained attention**: maintaining goal-relevant information, suppressing irrelevant stimuli, and keeping task engagement over time.
- **Executive function**: setting a goal, holding steps in mind, allocating attention, monitoring progress, and adjusting action.
- **Overall executive function model**: “该指标观察儿童在多步骤任务中设定目标、暂存步骤、分配注意、监控进度并根据反馈调整行动的综合认知控制能力。” Do not replace this definition with “大脑的高级指挥官”等比喻。
- **Inhibitory control**: pausing a dominant or impulsive response when the task requires waiting, stopping, or changing action.
- **Cognitive flexibility**: updating a response rule when conditions change or the original approach no longer works.

Model form:

> 【注意稳定性】抗干扰与深度聚焦：从认知控制角度，这一指标反映儿童对目标信息的持续维持、对无关刺激的抑制，以及在较长任务中保持投入的能力。注意维持与前额叶相关的执行控制过程有关。结合这项表现，家长可留意孩子在阅读、作业或多步骤活动中把注意力留在同一件事上的时间，以及需要怎样的分段或提醒。

### Creative Thinking And Inquiry

Use for 兴趣好奇心、问题好奇心、思维流畅性、思维灵活性、思维独创性、思维聚合性、设计、科学。

- **Fluency**: generating multiple possible ideas in a limited period.
- **Flexibility**: changing categories, perspectives, or strategies when a path is blocked.
- **Originality**: producing relatively uncommon but task-relevant ideas.
- **Convergent thinking**: filtering information and using rules to move toward a more suitable answer.
- **Inquiry**: approaching novelty, asking causal questions, and seeking evidence instead of stopping at a surface answer.

Translate into one concrete open question, material exploration, classification, or one-question-more situation. Do not claim that the child is “born creative” or universally avoids exploration.

### Learning And Reasoning

Use for 规则抽象能力、逻辑推理、文学、表演、社会、学习乐趣、学习意义感、学习自信感。

- **Rule abstraction**: extracting a relationship or rule from concrete examples and applying it to a new example.
- **Performance expression**: coordinating voice, facial expression, movement, and role understanding to communicate an idea in a public or semi-public setting. Describe it as expressive participation, not “艺术力” or a fixed stage personality.
- **Logical reasoning**: connecting conditions through cause, sequence, comparison, or spatial relations to reach a conclusion.
- **Academic self-efficacy**: the child’s current belief that effort and strategy can help with learning challenges.
- **Learning meaning**: connecting a learning activity with a personally understandable purpose or value.

Translate into examples such as explaining a solution, finding a rule in a changed question, telling a story, participating in a small group discussion, or naming why a task matters. Keep these as possibilities for observation, not reported facts.

### Emotion And School Experience

Use for 学校归属感、积极情绪、负性情绪、情感平衡。

- **School belonging**: feeling accepted, included, and psychologically connected to school and class life.
- **Negative emotion**: the frequency, intensity, or burden of worry, irritation, sadness, and similar unpleasant feelings. Follow the input direction exactly.
- **Emotional balance**: the relative balance between positive and unpleasant feelings, including the ability to recover after a setback.

For a potential area, use “可能更需要支持”“可留意出现频率、持续时间和恢复方式”. Never state that a child has an emotional disorder, has a family problem, or is always anxious.

## Rating Calibration

When the input uses `class_rank_percentile`:

- The supplied `level` is the conclusion. Do not infer the level from raw score.
- 优势区: describe a comparatively clear, stable current strength, then state the constructive support it can provide for learning, interaction, or self-management. Do not automatically append a “but under complex/high-pressure conditions it may weaken” caveat unless the input explicitly provides such evidence.
- 常态区: describe a stable current foundation, then explain how performance may vary when information load, rules, or task demands increase. Do not force a strength or a problem.
- 潜力区: describe a current support priority, normalize variability, and offer a small next step.
- Near a boundary: use cautious language such as “仍在建立”“需要更多练习”“可先从较小情境开始”.

## Non-Negotiable Boundaries

- Do not invent classroom events, family arguments, teacher comments, friends, previous attempts, or causes.
- Do not turn any one score into a personality label or a conclusion about brain development.
- Do not copy a retrieved case sentence verbatim. Borrow the method, not another child’s story.
