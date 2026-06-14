import { LegalPageLayout } from '../components/LegalDocument';
import { PRIVACY_POLICY } from '../content/legal';

/**
 * Public privacy policy page. Makes no authenticated API calls.
 *
 * @returns The rendered privacy policy.
 */
export default function PrivacyPolicyPage(): JSX.Element {
  return <LegalPageLayout content={PRIVACY_POLICY} />;
}
