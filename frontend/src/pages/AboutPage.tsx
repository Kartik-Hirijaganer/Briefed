import { LegalPageLayout } from '../components/LegalDocument';
import { ABOUT_CONTENT } from '../content/legal';

/**
 * Public about page. Makes no authenticated API calls.
 *
 * @returns The rendered about page.
 */
export default function AboutPage(): JSX.Element {
  return <LegalPageLayout content={ABOUT_CONTENT} />;
}
