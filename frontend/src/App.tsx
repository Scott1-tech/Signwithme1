import { Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { useAuth } from './hooks/useAuth';
import { ContractUpload } from './pages/ContractUpload';
import { Dashboard } from './pages/Dashboard';
import { FinalContract } from './pages/FinalContract';
import { Login } from './pages/Login';
import { ReviewPage } from './pages/ReviewPage';
import { ReviewQueue } from './pages/ReviewQueue';
import { SignaturePage } from './pages/SignaturePage';
import { TemplateManager } from './pages/TemplateManager';

function RequireAuth({ children, role }: { children: JSX.Element; role?: 'reviewer' | 'admin' }) {
  const { user, loading, isAtLeast } = useAuth();
  if (loading) return <p className="page">Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (role && !isAtLeast(role)) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="contracts/new" element={<ContractUpload />} />
        <Route path="contracts/:contractId/review" element={<ReviewPage />} />
        <Route path="contracts/:contractId/sign" element={<SignaturePage />} />
        <Route path="contracts/:contractId/final" element={<FinalContract />} />
        <Route
          path="review"
          element={
            <RequireAuth role="reviewer">
              <ReviewQueue />
            </RequireAuth>
          }
        />
        <Route
          path="templates"
          element={
            <RequireAuth role="admin">
              <TemplateManager />
            </RequireAuth>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
