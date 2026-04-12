import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import ConnectPage from "./pages/ConnectPage";
import LandingPage from "./pages/LandingPage";
import ModelPage from "./pages/ModelPage";
import QueryPage from "./pages/QueryPage";
import SchemaPage from "./pages/SchemaPage";

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        {/* Welcome / setup flow — standalone full-page routes */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/model" element={<ModelPage />} />
        <Route path="/connect" element={<ConnectPage />} />

        {/* App shell with persistent sidebar */}
        <Route element={<AppLayout />}>
          <Route path="/query" element={<QueryPage />} />
          <Route path="/schema" element={<SchemaPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
