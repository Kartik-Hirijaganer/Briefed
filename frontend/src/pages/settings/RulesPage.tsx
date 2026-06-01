import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';

import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import type { Schemas } from '../../api/types';

type Bucket = Schemas['EmailRow']['bucket'];
type MatchField =
  | 'from_email'
  | 'from_domain'
  | 'subject_contains'
  | 'subject_regex'
  | 'has_label'
  | 'topic_keyword';

interface MatchOption {
  readonly value: MatchField;
  readonly label: string;
  readonly placeholder: string;
}

interface RuleFormState {
  readonly id: string | null;
  readonly name: string;
  readonly priority: string;
  readonly matchField: MatchField;
  readonly matchValue: string;
  readonly category: Bucket;
  readonly confidence: string;
  readonly active: boolean;
}

const MATCH_OPTIONS: readonly MatchOption[] = [
  {
    value: 'from_email',
    label: 'Sender email',
    placeholder: 'person@example.com',
  },
  {
    value: 'from_domain',
    label: 'Sender domain',
    placeholder: 'example.com',
  },
  {
    value: 'subject_contains',
    label: 'Subject contains',
    placeholder: 'invoice',
  },
  {
    value: 'subject_regex',
    label: 'Subject regex',
    placeholder: 'invoice|receipt',
  },
  {
    value: 'has_label',
    label: 'Gmail label',
    placeholder: 'IMPORTANT',
  },
  {
    value: 'topic_keyword',
    label: 'Topic keyword',
    placeholder: 'security alert, password reset',
  },
];

const CATEGORY_LABEL: Record<Bucket, string> = {
  must_read: 'Must-Read',
  good_to_read: 'Good-to-Read',
  ignore: 'Ignore',
};

const EMPTY_FORM: RuleFormState = {
  id: null,
  name: '',
  priority: '100',
  matchField: 'from_email',
  matchValue: '',
  category: 'must_read',
  confidence: '0.9',
  active: true,
};

/**
 * Rules settings (`/settings/rules`). Provides CRUD over the rubric API with
 * first-class form controls instead of the retired raw-JSON prompts page.
 *
 * @returns The rendered rules editor.
 */
export default function RulesPage(): JSX.Element {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<RuleFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const rubricQuery = useQuery({
    queryKey: ['rubric'],
    queryFn: async () => unwrap(await api.GET('/api/v1/rubric')),
  });

  const saveRule = useMutation({
    mutationFn: async (body: Schemas['RubricRuleInput']) => {
      if (form.id) {
        return unwrap(
          await api.PUT('/api/v1/rubric/{rule_id}', {
            params: { path: { rule_id: form.id } },
            body,
          }),
        );
      }
      return unwrap(await api.POST('/api/v1/rubric', { body }));
    },
    onSuccess: () => {
      setForm(EMPTY_FORM);
      setFormError(null);
      void queryClient.invalidateQueries({ queryKey: ['rubric'] });
    },
  });

  const deleteRule = useMutation({
    mutationFn: async (ruleId: string): Promise<void> => {
      const result = await api.DELETE('/api/v1/rubric/{rule_id}', {
        params: { path: { rule_id: ruleId } },
      });
      if (result.error !== undefined) {
        throw new Error('Rule delete failed');
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['rubric'] });
    },
  });

  const submit = (): void => {
    const validation = validateForm(form);
    if (validation) {
      setFormError(validation);
      return;
    }
    saveRule.mutate(toRuleInput(form));
  };

  if (rubricQuery.isPending) return <Skeleton shape="block" />;
  if (rubricQuery.isError) {
    return (
      <ErrorState
        title="Could not load rules"
        detail={rubricQuery.error instanceof Error ? rubricQuery.error.message : undefined}
      />
    );
  }

  const rules = rubricQuery.data?.rules ?? [];

  return (
    <section className="flex flex-col gap-4">
      {formError ? (
        <Alert tone="danger" title="Rule is incomplete">
          <p>{formError}</p>
        </Alert>
      ) : null}
      {saveRule.isError ? (
        <Alert tone="danger" title="Could not save rule">
          <p>{saveRule.error.message}</p>
        </Alert>
      ) : null}
      {deleteRule.isError ? (
        <Alert tone="danger" title="Could not delete rule">
          <p>{deleteRule.error.message}</p>
        </Alert>
      ) : null}

      <Card className="flex flex-col gap-4">
        <header className="max-w-[var(--measure)]">
          <h2 className="text-lg font-semibold text-fg">{form.id ? 'Edit rule' : 'Create rule'}</h2>
          <p className="text-sm text-fg-muted">
            Rules run before the LLM, so common sender, subject, label, and topic patterns are
            sorted instantly.
          </p>
        </header>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          <Field label="Name" required>
            <input
              type="text"
              value={form.name}
              onChange={(event) => setFormField(setForm, { name: event.target.value })}
              className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
            />
          </Field>

          <Field label="Match">
            <select
              value={form.matchField}
              onChange={(event) =>
                setFormField(setForm, { matchField: event.target.value as MatchField })
              }
              className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
            >
              {MATCH_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Match value" required>
            <input
              type="text"
              value={form.matchValue}
              placeholder={matchPlaceholder(form.matchField)}
              onChange={(event) => setFormField(setForm, { matchValue: event.target.value })}
              className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
            />
          </Field>

          <Field label="Category">
            <select
              value={form.category}
              onChange={(event) =>
                setFormField(setForm, { category: event.target.value as Bucket })
              }
              className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
            >
              {Object.entries(CATEGORY_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Confidence">
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={form.confidence}
              onChange={(event) => setFormField(setForm, { confidence: event.target.value })}
              className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
            />
          </Field>

          <Field label="Priority">
            <input
              type="number"
              min="0"
              max="100000"
              step="10"
              value={form.priority}
              onChange={(event) => setFormField(setForm, { priority: event.target.value })}
              className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
            />
          </Field>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(event) => setFormField(setForm, { active: event.target.checked })}
            />
            Active
          </label>
          <div className="flex items-center gap-2">
            {form.id ? (
              <Button variant="ghost" size="sm" onClick={() => setForm(EMPTY_FORM)}>
                Cancel edit
              </Button>
            ) : null}
            <Button
              variant="primary"
              size="sm"
              onClick={submit}
              loading={saveRule.isPending}
              disabled={saveRule.isPending}
            >
              {form.id ? 'Save rule' : 'Create rule'}
            </Button>
          </div>
        </div>
      </Card>

      {rules.length === 0 ? (
        <EmptyState
          icon="bolt"
          title="No rules defined yet"
          description="Create a sender, subject, label, or topic rule to sort recurring mail before the LLM runs."
        />
      ) : (
        <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {rules.map((rule) => (
            <li key={rule.id}>
              <RuleCard
                rule={rule}
                deletePending={deleteRule.isPending}
                onEdit={() => setForm(ruleToForm(rule))}
                onDelete={() => deleteRule.mutate(rule.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface RuleCardProps {
  readonly rule: Schemas['RubricRule'];
  readonly deletePending: boolean;
  readonly onEdit: () => void;
  readonly onDelete: () => void;
}

/**
 * Render one saved rubric rule with edit/delete actions.
 *
 * @param props - Component props.
 * @returns The rendered rule card.
 */
function RuleCard(props: RuleCardProps): JSX.Element {
  const { rule, deletePending, onEdit, onDelete } = props;
  const label = String(rule.action.label ?? 'ignore') as Bucket;
  return (
    <Card className="flex h-full flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-fg">{rule.name}</h3>
          <p className="text-xs text-fg-muted">Priority {rule.priority}</p>
        </div>
        <Badge tone={rule.active ? 'accent' : 'neutral'}>
          {rule.active ? 'Active' : 'Inactive'}
        </Badge>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">{describeMatch(rule.match)}</Badge>
        <Badge tone={label === 'must_read' ? 'accent' : 'neutral'}>
          {CATEGORY_LABEL[label] ?? label}
        </Badge>
        <Badge tone="neutral">{formatConfidence(rule.action.confidence)} confidence</Badge>
      </div>
      <div className="mt-auto flex items-center justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onEdit}>
          Edit
        </Button>
        <Button variant="destructive" size="sm" onClick={onDelete} disabled={deletePending}>
          Delete
        </Button>
      </div>
    </Card>
  );
}

/**
 * Update a partial form state with React's functional setState shape.
 *
 * @param setForm - State setter.
 * @param patch - Partial form patch.
 */
function setFormField(
  setForm: Dispatch<SetStateAction<RuleFormState>>,
  patch: Partial<RuleFormState>,
): void {
  setForm((current) => ({ ...current, ...patch }));
}

/**
 * Validate the rule form before building the API body.
 *
 * @param form - Current form state.
 * @returns Error message, or `null` when valid.
 */
function validateForm(form: RuleFormState): string | null {
  const confidence = Number.parseFloat(form.confidence);
  const priority = Number.parseInt(form.priority, 10);
  if (!form.name.trim()) return 'Name is required.';
  if (!form.matchValue.trim()) return 'Match value is required.';
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
    return 'Confidence must be between 0 and 1.';
  }
  if (!Number.isFinite(priority) || priority < 0 || priority > 100_000) {
    return 'Priority must be between 0 and 100000.';
  }
  return null;
}

/**
 * Convert form state into the rubric API request body.
 *
 * @param form - Validated form state.
 * @returns API request payload.
 */
function toRuleInput(form: RuleFormState): Schemas['RubricRuleInput'] {
  return {
    name: form.name.trim(),
    priority: Number.parseInt(form.priority, 10),
    match: {
      [form.matchField]:
        form.matchField === 'topic_keyword' ? splitList(form.matchValue) : form.matchValue.trim(),
    },
    action: {
      label: form.category,
      confidence: Number.parseFloat(form.confidence),
    },
    active: form.active,
  };
}

/**
 * Convert an API rule row into editable form state.
 *
 * @param rule - Rule row from `/api/v1/rubric`.
 * @returns Form state for editing.
 */
function ruleToForm(rule: Schemas['RubricRule']): RuleFormState {
  const [field, value] = Object.entries(rule.match)[0] ?? ['from_email', ''];
  const matchField = isMatchField(field) ? field : 'from_email';
  const category = isBucket(rule.action.label) ? rule.action.label : 'ignore';
  return {
    id: rule.id,
    name: rule.name,
    priority: String(rule.priority),
    matchField,
    matchValue: Array.isArray(value) ? value.map(String).join(', ') : String(value ?? ''),
    category,
    confidence: String(rule.action.confidence ?? 0.9),
    active: rule.active,
  };
}

/**
 * Return placeholder text for the selected match field.
 *
 * @param field - Selected match field.
 * @returns Placeholder copy.
 */
function matchPlaceholder(field: MatchField): string {
  return MATCH_OPTIONS.find((option) => option.value === field)?.placeholder ?? '';
}

/**
 * Describe a match predicate in compact human-readable text.
 *
 * @param match - Rule match dictionary.
 * @returns Compact rule description.
 */
function describeMatch(match: Schemas['RubricRule']['match']): string {
  const [field, value] = Object.entries(match)[0] ?? ['match', ''];
  const label = MATCH_OPTIONS.find((option) => option.value === field)?.label ?? field;
  const displayValue = Array.isArray(value) ? value.join(', ') : String(value ?? '');
  return `${label}: ${displayValue}`;
}

/**
 * Format an action confidence value.
 *
 * @param value - Unknown confidence value from the API.
 * @returns Percentage text.
 */
function formatConfidence(value: unknown): string {
  const confidence = Number(value ?? 0.9);
  if (!Number.isFinite(confidence)) return '90%';
  return `${Math.round(confidence * 100)}%`;
}

/**
 * Split a comma-separated keyword list.
 *
 * @param raw - Raw input string.
 * @returns Trimmed non-empty values.
 */
function splitList(raw: string): string[] {
  return raw
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

/**
 * Test whether an arbitrary key is a supported form match field.
 *
 * @param value - Candidate field.
 * @returns Whether the value is supported.
 */
function isMatchField(value: string): value is MatchField {
  return MATCH_OPTIONS.some((option) => option.value === value);
}

/**
 * Test whether an arbitrary value is one of the three public buckets.
 *
 * @param value - Candidate bucket.
 * @returns Whether the value is supported.
 */
function isBucket(value: unknown): value is Bucket {
  return value === 'must_read' || value === 'good_to_read' || value === 'ignore';
}
