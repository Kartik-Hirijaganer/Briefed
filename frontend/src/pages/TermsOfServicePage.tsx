import { LegalPageLayout } from '../components/LegalDocument';
import { TERMS_OF_SERVICE } from '../content/legal';

/**
 * Public terms of service page. Makes no authenticated API calls.
 *
 * @returns The rendered terms of service.
 */
export default function TermsOfServicePage(): JSX.Element {
  return <LegalPageLayout content={TERMS_OF_SERVICE} />;
}
