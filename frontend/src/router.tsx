import { createBrowserRouter, Navigate } from 'react-router-dom';

import AboutPage from './pages/AboutPage';
import DashboardPage from './pages/DashboardPage';
import HistoryPage from './pages/HistoryPage';
import HistoryRunDetailPage from './pages/HistoryRunDetailPage';
import HomePage from './pages/HomePage';
import LoginPage from './pages/LoginPage';
import NotFoundPage from './pages/NotFoundPage';
import OAuthCallbackPage from './pages/OAuthCallbackPage';
import PrivacyPolicyPage from './pages/PrivacyPolicyPage';
import TermsOfServicePage from './pages/TermsOfServicePage';
import UnsubscribePage from './pages/UnsubscribePage';
import AccountsPage from './pages/settings/AccountsPage';
import PreferencesPage from './pages/settings/PreferencesPage';
import RulesPage from './pages/settings/RulesPage';
import SchedulePage from './pages/settings/SchedulePage';
import SettingsLayout from './pages/settings/SettingsLayout';

import { useAppPath } from './routing/routeBase';
import { AppShell } from './shell/AppShell';
import { DemoShell } from './shell/DemoShell';

/**
 * Top-level browser router. Routes keyed to the §10 information
 * architecture. Settings is nested so `/app/settings` always redirects to
 * `/app/settings/accounts`.
 */
export const router = createBrowserRouter([
  { path: '/', element: <HomePage /> },
  { path: '/about', element: <AboutPage /> },
  { path: '/privacy', element: <PrivacyPolicyPage /> },
  { path: '/terms', element: <TermsOfServicePage /> },
  { path: '/login', element: <LoginPage /> },
  { path: '/oauth/callback', element: <OAuthCallbackPage /> },
  {
    path: '/demo',
    element: <DemoShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'unsubscribe', element: <UnsubscribePage /> },
      { path: 'history', element: <HistoryPage /> },
      { path: 'history/:runId', element: <HistoryRunDetailPage /> },
      {
        path: 'settings',
        element: <SettingsLayout />,
        children: [
          { index: true, element: <SettingsIndexRedirect /> },
          { path: 'accounts', element: <AccountsPage /> },
          { path: 'schedule', element: <SchedulePage /> },
          { path: 'rules', element: <RulesPage /> },
          { path: 'preferences', element: <PreferencesPage /> },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
  {
    path: '/app',
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'unsubscribe', element: <UnsubscribePage /> },
      { path: 'history', element: <HistoryPage /> },
      { path: 'history/:runId', element: <HistoryRunDetailPage /> },
      {
        path: 'settings',
        element: <SettingsLayout />,
        children: [
          { index: true, element: <SettingsIndexRedirect /> },
          { path: 'accounts', element: <AccountsPage /> },
          { path: 'schedule', element: <SchedulePage /> },
          { path: 'rules', element: <RulesPage /> },
          { path: 'preferences', element: <PreferencesPage /> },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]);

function SettingsIndexRedirect(): JSX.Element {
  const appPath = useAppPath();
  return <Navigate to={appPath('settings/accounts')} replace />;
}
