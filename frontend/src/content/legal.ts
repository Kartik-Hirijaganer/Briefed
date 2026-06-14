/**
 * One section in a structured public content document.
 */
export interface LegalSection {
  /** Stable fragment id used by headings and future deep links. */
  readonly id: string;
  /** Section heading rendered as an h2. */
  readonly title: string;
  /** Body paragraphs rendered in order. */
  readonly paragraphs: readonly string[];
}

/**
 * Structured legal or public product content rendered by LegalDocument.
 */
export interface LegalContent {
  /** Document heading rendered as an h1. */
  readonly title: string;
  /** Optional policy version for legal documents. */
  readonly version?: number;
  /** Optional effective date for legal documents. */
  readonly effectiveDate?: string;
  /** Introductory paragraphs shown before the first section. */
  readonly intro: readonly string[];
  /** Ordered document sections. */
  readonly sections: readonly LegalSection[];
}

export const PRIVACY_POLICY_VERSION = 1;
export const TERMS_VERSION = 1;
export const POLICY_EFFECTIVE_DATE = '2026-06-13';

export const CONSENT_SUMMARY = [
  'Briefed requests gmail.readonly to ingest Gmail messages and gmail.modify only for user-initiated mark-read actions.',
  'Briefed also requests userinfo.email, userinfo.profile, and openid to identify the connected Google account and keep your Briefed session tied to that account.',
  'OAuth tokens and stored email bodies, summaries, and rationales are KMS-envelope encrypted; metadata needed for sorting and display is stored in the database.',
  'LLM processing is routed through OpenRouter to Google Gemini 2.5 Flash first, with Anthropic Claude Haiku 4.5 as fallback.',
  'Optional prompt redaction is best-effort identity and pattern-based removal; it reduces obvious sensitive tokens but does not guarantee PII removal.',
  'Briefed is not for HIPAA-regulated healthcare data or protected health information.',
] as const;

export const PRIVACY_POLICY = {
  title: 'Privacy Policy',
  version: PRIVACY_POLICY_VERSION,
  effectiveDate: POLICY_EFFECTIVE_DATE,
  intro: [
    'Briefed is operated by Kartik Hirijaganer as an individual portfolio project. Questions or privacy requests can be sent to kartikhirijaganer@gmail.com.',
    'This policy explains how Briefed handles information when you use the synthetic demo or connect a Gmail account.',
  ],
  sections: [
    {
      id: 'what-briefed-does',
      title: 'What Briefed Does',
      paragraphs: [
        'Briefed reads Gmail messages you choose to connect, classifies them into priority buckets, summarizes important messages, and recommends noisy senders to review. Briefed is recommend-only in this release: it does not send email, archive messages, delete messages, or click unsubscribe links on your behalf.',
        'The demo path uses synthetic mailbox data. It is designed so recruiters and reviewers can try the product without connecting a Google account. Demo content is not your Gmail data.',
      ],
    },
    {
      id: 'gmail-data-and-scopes',
      title: 'Gmail Data and Scopes',
      paragraphs: [
        'If you choose Connect Gmail, Briefed processes real Gmail data for the connected account. The OAuth scopes requested are https://www.googleapis.com/auth/gmail.readonly, https://www.googleapis.com/auth/gmail.modify, https://www.googleapis.com/auth/userinfo.email, https://www.googleapis.com/auth/userinfo.profile, and openid.',
        'The gmail.readonly scope lets Briefed ingest message metadata and message content for triage and summaries. The gmail.modify scope is used only when you explicitly ask Briefed to mark selected Gmail messages as read. The userinfo.email, userinfo.profile, and openid scopes identify the connected Google account and keep the Briefed session tied to that account.',
      ],
    },
    {
      id: 'data-stored',
      title: 'Data Stored',
      paragraphs: [
        'Briefed stores account records, sync cursors, message metadata needed to display and sort the inbox, classification results, summaries, unsubscribe recommendations, settings, and prompt call logs. OAuth access and refresh tokens are envelope-encrypted with an AWS KMS customer-managed key before storage.',
        'Stored email bodies and email-derived content such as summaries and rationales are envelope-encrypted with the content KMS key where the application stores those payloads. The database can still contain non-content metadata needed for product behavior, such as sender, subject, timestamps, labels, scores, and status fields.',
      ],
    },
    {
      id: 'llm-processing-and-redaction',
      title: 'LLM Processing and Redaction',
      paragraphs: [
        'Briefed sends prompt content through OpenRouter for model processing. The primary model route is Google Gemini 2.5 Flash. If the primary route fails or is unavailable, Briefed can fall back to Anthropic Claude Haiku 4.5.',
        'When redaction is enabled, Briefed runs best-effort identity and pattern-based removal before sending prompts. The implementation replaces known user identity strings first, then common patterns such as email addresses, URLs, phone numbers, U.S. Social Security numbers, ZIP codes, and IP addresses. This reduces obvious sensitive tokens but does not guarantee that all personal information is removed.',
      ],
    },
    {
      id: 'google-limited-use',
      title: 'Google Limited Use Disclosure',
      paragraphs: [
        "Briefed's use and transfer of information received from Google APIs to any other app adheres to the Google API Services User Data Policy, including the Limited Use requirements.",
        'Briefed uses Google user data only to provide and improve the Gmail triage features you request. Briefed does not sell Google user data. Briefed does not use Google user data for advertising. Briefed does not allow humans to read Google user data except when you explicitly ask for help, for security or abuse investigation, to comply with law, or for internal operations where the data has been aggregated and de-identified.',
      ],
    },
    {
      id: 'subprocessors',
      title: 'Subprocessors',
      paragraphs: [
        'Briefed relies on AWS for backend hosting, queues, storage, and KMS encryption; Supabase for Postgres database hosting; Google for OAuth and Gmail APIs; OpenRouter for LLM routing; Google Gemini and Anthropic Claude as model providers; and Vercel for public frontend hosting when that deployment path is enabled.',
        'These providers process data only as needed to provide the service functions described in this policy.',
      ],
    },
    {
      id: 'retention-and-deletion',
      title: 'Retention, Deletion, and Revocation',
      paragraphs: [
        'Briefed keeps connected-account data while the account remains connected and while cached results are needed to show the dashboard, history, settings, and recommendations. You can disconnect a mailbox from Settings, Gmail accounts. Disconnecting removes Briefed local OAuth tokens and account-scoped cached emails, summaries, classifications, and recommendations, then marks the account as revoked for reconnect or final removal.',
        'After an account is disconnected, you can remove the disconnected account entry from the same settings screen. You can also revoke Briefed access from your Google Account security settings. Revocation prevents future Gmail access, but it does not automatically delete already-cached Briefed data unless you also disconnect or remove the account in Briefed.',
      ],
    },
    {
      id: 'security',
      title: 'Security',
      paragraphs: [
        'Briefed uses HTTPS in deployment, signed session cookies, CSRF protection for state-changing browser requests, AWS KMS envelope encryption for OAuth tokens and stored content payloads, and scoped backend handlers for account ownership checks.',
        'No system can guarantee perfect security. If you believe Briefed has exposed data or credentials, contact kartikhirijaganer@gmail.com so the operator can investigate and revoke affected access.',
      ],
    },
    {
      id: 'no-sale-no-hipaa',
      title: 'No Sale and No HIPAA Use',
      paragraphs: [
        'Briefed does not sell your data.',
        'Briefed is not designed for HIPAA-regulated healthcare data, protected health information, or other regulated data requiring a dedicated compliance program. Do not connect mailboxes that you need to process under HIPAA.',
      ],
    },
    {
      id: 'changes',
      title: 'Changes And Versioning',
      paragraphs: [
        'This Privacy Policy is versioned. If Briefed materially changes how Gmail data, LLM routing, retention, or subprocessors work, the policy version will be updated and users may be asked to accept the new version before continuing to use the real Gmail path.',
      ],
    },
    {
      id: 'contact',
      title: 'Contact',
      paragraphs: [
        'For privacy questions, deletion requests, or security concerns, email Kartik Hirijaganer at kartikhirijaganer@gmail.com.',
      ],
    },
  ],
} as const satisfies LegalContent;

export const TERMS_OF_SERVICE = {
  title: 'Terms of Service',
  version: TERMS_VERSION,
  effectiveDate: POLICY_EFFECTIVE_DATE,
  intro: [
    'These Terms govern your use of Briefed. Briefed is operated by Kartik Hirijaganer as an individual portfolio project.',
    'By using the demo, connecting Gmail, or using the authenticated app, you agree to these Terms.',
  ],
  sections: [
    {
      id: 'service',
      title: 'Service Description',
      paragraphs: [
        'Briefed is an AI-assisted Gmail triage tool. It ingests connected Gmail messages, classifies message priority, summarizes selected content, and recommends senders to review. The demo uses synthetic data and does not require a Google account.',
        'Briefed is recommend-only in this release. It does not send email, archive messages, delete messages, or click unsubscribe links on your behalf. The gmail.modify scope is reserved for user-initiated mark-read actions.',
      ],
    },
    {
      id: 'accounts-and-authority',
      title: 'Accounts and Authority',
      paragraphs: [
        'You may connect only Gmail accounts that you own or are authorized to administer. You are responsible for maintaining control of the Google account, browser session, and device used to access Briefed.',
      ],
    },
    {
      id: 'ai-output',
      title: 'AI Output Disclaimer',
      paragraphs: [
        'Briefed uses AI models to classify and summarize email. AI output can be incomplete, stale, misleading, or wrong. You are responsible for reviewing important messages directly in Gmail before taking action.',
        'Briefed does not provide legal, financial, medical, employment, or other professional advice.',
      ],
    },
    {
      id: 'acceptable-use',
      title: 'Acceptable Use',
      paragraphs: [
        "Do not use Briefed to violate law, infringe privacy or intellectual-property rights, process another person's mailbox without authority, attack or disrupt the service, reverse engineer security controls, or route data that requires compliance controls Briefed does not provide.",
      ],
    },
    {
      id: 'no-hipaa',
      title: 'No HIPAA-Regulated Use',
      paragraphs: [
        'Briefed is not designed for protected health information or HIPAA-regulated healthcare workflows. Do not connect mailboxes used to process PHI or data that requires a business associate agreement.',
      ],
    },
    {
      id: 'google-api-compliance',
      title: 'Google API Compliance',
      paragraphs: [
        'When using the Gmail path, you must comply with Google account rules and applicable Google API terms. Briefed may pause, disconnect, or refuse access if continued use would violate those requirements or create security, abuse, or compliance risk.',
      ],
    },
    {
      id: 'availability-and-changes',
      title: 'Availability and Changes',
      paragraphs: [
        'Briefed is provided as an individual portfolio project and may change, pause, or stop at any time. Features may be incomplete, experimental, or unavailable while the project is under active development.',
      ],
    },
    {
      id: 'warranty-and-liability',
      title: 'As-Is Service, No Warranty, and Liability Limit',
      paragraphs: [
        'Briefed is provided as-is and as available, without warranties of any kind. To the fullest extent permitted by law, Briefed and its operator are not liable for indirect, incidental, consequential, special, exemplary, or punitive damages, lost profits, lost data, or business interruption arising from use of the service.',
      ],
    },
    {
      id: 'termination',
      title: 'Termination',
      paragraphs: [
        'You can stop using Briefed at any time. You can disconnect or remove connected Gmail accounts from Settings, Gmail accounts, and you can revoke Google access from your Google Account security settings. The operator may suspend or terminate access if needed to protect the service, comply with law, or prevent misuse.',
      ],
    },
    {
      id: 'law',
      title: 'Governing Law',
      paragraphs: [
        'These Terms are governed by Maryland law and applicable U.S. federal law, without regard to conflict-of-law rules.',
      ],
    },
    {
      id: 'contact',
      title: 'Contact',
      paragraphs: ['Questions about these Terms can be sent to kartikhirijaganer@gmail.com.'],
    },
  ],
} as const satisfies LegalContent;

export const ABOUT_CONTENT = {
  title: 'About Briefed',
  intro: [
    'Briefed is a personal AI email agent built to turn a noisy Gmail inbox into a ranked brief: what needs attention, what can wait, what can be ignored, and which senders may be worth muting.',
    'The project is designed for review and hiring conversations as much as day-to-day use. The public demo uses synthetic inbox data so anyone can inspect the workflow without connecting a Google account.',
  ],
  sections: [
    {
      id: 'product-principles',
      title: 'Product Principles',
      paragraphs: [
        'Briefed is user-controlled. It explains why a message or sender was ranked the way it was, but destructive actions require explicit user confirmation and are outside the 1.0.0 recommend-only path.',
        'Briefed separates the synthetic demo path from the real Gmail path. The demo is safe for public review. The Gmail path is for users who understand and accept that their mailbox data will be processed under the Privacy Policy and Terms.',
      ],
    },
    {
      id: 'technical-shape',
      title: 'Technical Shape',
      paragraphs: [
        'The backend is FastAPI and Python running in AWS Lambda with SQS fan-out workers. The frontend is a React and TypeScript PWA. Gmail data is stored in Supabase Postgres with AWS KMS envelope encryption for OAuth tokens and stored content payloads.',
        'LLM calls flow through OpenRouter with Google Gemini 2.5 Flash as the primary route and Anthropic Claude Haiku 4.5 as fallback. Optional prompt redaction is best-effort identity and pattern-based removal before prompts leave Briefed infrastructure.',
      ],
    },
    {
      id: 'operator',
      title: 'Operator',
      paragraphs: [
        'Briefed is operated by Kartik Hirijaganer. For questions about the project, privacy, or access, email kartikhirijaganer@gmail.com.',
      ],
    },
  ],
} as const satisfies LegalContent;
