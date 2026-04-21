import { createBrowserRouter, Navigate } from 'react-router-dom';

import DashboardPage from './pages/DashboardPage';
import HistoryPage from './pages/HistoryPage';
import JobsPage from './pages/JobsPage';
import LoginPage from './pages/LoginPage';
import NewsPage from './pages/NewsPage';
import NotFoundPage from './pages/NotFoundPage';
import OAuthCallbackPage from './pages/OAuthCallbackPage';
import TriagePage from './pages/TriagePage';
import UnsubscribePage from './pages/UnsubscribePage';
import AccountsPage from './pages/settings/AccountsPage';
import PreferencesPage from './pages/settings/PreferencesPage';
import PromptsPage from './pages/settings/PromptsPage';
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
      { path: 'must-read', element: <TriagePage bucket="must_read" /> },
      { path: 'good-to-read', element: <TriagePage bucket="good_to_read" /> },
      { path: 'ignore', element: <TriagePage bucket="ignore" /> },
      { path: 'waste', element: <TriagePage bucket="waste" /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: 'news', element: <NewsPage /> },
      { path: 'unsubscribe', element: <UnsubscribePage /> },
      { path: 'history', element: <HistoryPage /> },
      {
        path: 'settings',
        element: <SettingsLayout />,
        children: [
          { index: true, element: <Navigate to="/settings/accounts" replace /> },
          { path: 'accounts', element: <AccountsPage /> },
          { path: 'preferences', element: <PreferencesPage /> },
          { path: 'prompts', element: <PromptsPage /> },
          { path: 'schedule', element: <SchedulePage /> },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]);
