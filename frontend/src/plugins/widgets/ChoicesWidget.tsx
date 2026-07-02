import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUp, Pencil } from "lucide-react";
import type { ResultRenderContext } from "@/plugins/ResultRegistry";
import "./choices-widget.css";

interface ChoiceOption {
  id: string;
  label: string;
}

interface ChoiceQuestion {
  id: string;
  prompt: string;
  allowMultiple: boolean;
  allowOpenText: boolean;
  openTextPlaceholder: string;
  options: ChoiceOption[];
}

interface ChoicesWidgetProps {
  context: ResultRenderContext;
  payload: Record<string, unknown>;
}

const WIDGET_MAKE_CHOICES_MARKER = "WIDGET_MAKE_CHOICES_ANSWERS";

interface SubmittedAnswer {
  question_id: string;
  question_prompt: string;
  selected_options: string[];
  open_text: string | null;
}

function normalizeQuestions(payload: Record<string, unknown>): ChoiceQuestion[] {
  const rawQuestions = Array.isArray(payload.questions) ? payload.questions : [];
  const questions: ChoiceQuestion[] = [];

  for (let questionIndex = 0; questionIndex < rawQuestions.length; questionIndex += 1) {
    const rawQuestion = rawQuestions[questionIndex];
    if (!rawQuestion || typeof rawQuestion !== "object" || Array.isArray(rawQuestion)) {
      continue;
    }
    const question = rawQuestion as Record<string, unknown>;
    const prompt = String(question.prompt ?? "").trim();
    if (!prompt) {
      continue;
    }

    const rawOptions = Array.isArray(question.options) ? question.options : [];
    const options: ChoiceOption[] = [];
    for (let optionIndex = 0; optionIndex < rawOptions.length; optionIndex += 1) {
      const rawOption = rawOptions[optionIndex];
      if (!rawOption || typeof rawOption !== "object" || Array.isArray(rawOption)) {
        continue;
      }
      const option = rawOption as Record<string, unknown>;
      const label = String(option.label ?? "").trim();
      if (!label) {
        continue;
      }
      const id = String(option.id ?? "").trim() || `option_${questionIndex + 1}_${optionIndex + 1}`;
      options.push({ id, label });
    }

    if (!options.length) {
      continue;
    }

    questions.push({
      id: String(question.id ?? "").trim() || `question_${questionIndex + 1}`,
      prompt,
      allowMultiple: Boolean(question.allow_multiple ?? true),
      allowOpenText: Boolean(question.allow_open_text ?? false),
      openTextPlaceholder: String(question.open_text_placeholder ?? "").trim(),
      options,
    });
  }

  return questions;
}

function buildSubmittedAnswers(
  questions: ChoiceQuestion[],
  selectedByQuestion: Record<string, string[]>,
  openAnswerByQuestion: Record<string, string>
): SubmittedAnswer[] {
  const answers: SubmittedAnswer[] = [];

  for (const question of questions) {
    const selectedIds = selectedByQuestion[question.id] ?? [];
    const selectedLabels = question.options
      .filter((option) => selectedIds.includes(option.id))
      .map((option) => option.label);
    const openAnswer = String(openAnswerByQuestion[question.id] ?? "").trim();
    if (!selectedLabels.length && !openAnswer) {
      continue;
    }
    answers.push({
      question_id: question.id,
      question_prompt: question.prompt,
      selected_options: selectedLabels,
      open_text: openAnswer || null,
    });
  }

  return answers;
}

function buildVisibleUserMessage(answers: SubmittedAnswer[]): string {
  const lines: string[] = [];
  for (const answer of answers) {
    const answerParts: string[] = [];
    if (answer.selected_options.length) {
      answerParts.push(answer.selected_options.join(", "));
    }
    if (answer.open_text) {
      answerParts.push(answer.open_text);
    }
    lines.push(`- ${answer.question_prompt}: ${answerParts.join(" | ")}`);
  }
  return lines.join("\n");
}

function buildMachinePayload(answers: SubmittedAnswer[]): string {
  return `${WIDGET_MAKE_CHOICES_MARKER}\n${JSON.stringify({ answers }, null, 2)}`;
}

function buildSubmittedPreview(
  questions: ChoiceQuestion[],
  selectedByQuestion: Record<string, string[]>,
  openAnswerByQuestion: Record<string, string>
): string {
  const lines: string[] = [];
  for (const question of questions) {
    const selectedIds = selectedByQuestion[question.id] ?? [];
    const openAnswer = String(openAnswerByQuestion[question.id] ?? "").trim();
    if (!selectedIds.length && !openAnswer) {
      continue;
    }
    lines.push(`- ${question.prompt}`);
  }
  return lines.join("\n");
}

export function ChoicesWidget({ context, payload }: ChoicesWidgetProps) {
  const { t } = useTranslation();
  const questions = useMemo(() => normalizeQuestions(payload), [payload]);
  const [selectedByQuestion, setSelectedByQuestion] = useState<Record<string, string[]>>({});
  const [openInputByQuestion, setOpenInputByQuestion] = useState<Record<string, boolean>>({});
  const [openAnswerByQuestion, setOpenAnswerByQuestion] = useState<Record<string, string>>({});
  const [submittedPreview, setSubmittedPreview] = useState<string>("");

  if (!questions.length) {
    return null;
  }

  const hasAnyAnswer = questions.some((question) => {
    const selected = selectedByQuestion[question.id] ?? [];
    const openAnswer = String(openAnswerByQuestion[question.id] ?? "").trim();
    return selected.length > 0 || openAnswer.length > 0;
  });

  const toggleOption = (question: ChoiceQuestion, optionId: string): void => {
    setSelectedByQuestion((currentState) => {
      const selected = currentState[question.id] ?? [];
      const isSelected = selected.includes(optionId);
      if (question.allowMultiple) {
        return {
          ...currentState,
          [question.id]: isSelected
            ? selected.filter((id) => id !== optionId)
            : [...selected, optionId],
        };
      }
      return {
        ...currentState,
        [question.id]: isSelected ? [] : [optionId],
      };
    });
  };

  const handleSubmit = (): void => {
    const answers = buildSubmittedAnswers(questions, selectedByQuestion, openAnswerByQuestion);
    if (!answers.length || !context.submitUserMessage) {
      return;
    }
    const visibleMessage = buildVisibleUserMessage(answers);
    const message = `${visibleMessage}\n\n${buildMachinePayload(answers)}`;
    setSubmittedPreview(buildSubmittedPreview(questions, selectedByQuestion, openAnswerByQuestion));
    context.submitUserMessage(message);
  };

  if (submittedPreview) {
    return (
      <section className="core-choices-card">
        <pre className="core-choices-submitted">{submittedPreview}</pre>
      </section>
    );
  }

  return (
    <section className="core-choices-card">
      <div className="core-choices-layout">
        <div className="core-choices-content">
          {questions.map((question) => {
            const selected = selectedByQuestion[question.id] ?? [];
            const openVisible = openInputByQuestion[question.id] ?? false;
            const openValue = openAnswerByQuestion[question.id] ?? "";
            return (
              <div key={question.id} className="core-choice-question">
                <p className="core-choice-prompt">{question.prompt}</p>
                <div className="core-choice-options">
                  {question.options.map((option) => {
                    const isSelected = selected.includes(option.id);
                    return (
                      <button
                        key={option.id}
                        type="button"
                        className={`core-choice-chip ${isSelected ? "is-selected" : ""}`}
                        onClick={() => toggleOption(question, option.id)}
                      >
                        {option.label}
                      </button>
                    );
                  })}
                  {question.allowOpenText ? (
                    <button
                      type="button"
                      className={`core-choice-open-toggle ${openVisible ? "is-selected" : ""}`}
                      onClick={() =>
                        setOpenInputByQuestion((currentState) => ({
                          ...currentState,
                          [question.id]: !openVisible,
                        }))
                      }
                      aria-label={t("chat:choicesEnableOpen")}
                    >
                      <Pencil className="core-choice-open-icon" aria-hidden />
                    </button>
                  ) : null}
                </div>
                {question.allowOpenText && openVisible ? (
                  <input
                    type="text"
                    value={openValue}
                    onChange={(event) =>
                      setOpenAnswerByQuestion((currentState) => ({
                        ...currentState,
                        [question.id]: event.target.value,
                      }))
                    }
                    placeholder={question.openTextPlaceholder || t("chat:choicesOpenPlaceholder")}
                    className="core-choice-input"
                  />
                ) : null}
              </div>
            );
          })}
        </div>
        <div className="core-choices-submit-col">
          <button
            type="button"
            className="core-choices-submit"
            onClick={handleSubmit}
            disabled={!hasAnyAnswer || !context.submitUserMessage}
            aria-label={t("chat:choicesSubmit")}
          >
            <ArrowUp className="core-choices-submit-icon" aria-hidden />
          </button>
        </div>
      </div>
    </section>
  );
}
