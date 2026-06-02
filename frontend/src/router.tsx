import { createBrowserRouter, Navigate } from 'react-router-dom';

import DashboardPage from './pages/DashboardPage';
import HistoryPage from './pages/HistoryPage';
import HistoryRunDetailPage from './pages/HistoryRunDetailPage';
import LoginPage from './pages/LoginPage';
import NotFoundPage from './pages/NotFoundPage';
import OAuthCallbackPage from './pages/OAuthCallbackPage';
import UnsubscribePage from './pages/UnsubscribePage';
import AccountsPage from './pages/settings/AccountsPage';
import PreferencesPage from './pages/settings/PreferencesPage';
import RulesPage from './pages/settings/RulesPage';
import SchedulePage from './pages/settings/SchedulePage';
import SettingsLayout from './pages/settings/SettingsLayout';

import { AppShell } from './shell/AppShell';

/**
 * Top-level browser router. Routes keyed to the §10 information
 * architecture. Settings is nested so `/settings` always redirects to
 * `/settings/accounts`.
 */
export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/oauth/callback', element: <OAuthCallbackPage /> },
  {
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
          { index: true, element: <Navigate to="/settings/accounts" replace /> },
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
