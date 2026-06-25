import { Routes, Route } from "react-router-dom";

import Layout from "./components/Layout";
import SearchPage from "./pages/SearchPage";
import GraphExplorerPage from "./pages/GraphExplorerPage";
import StatsPage from "./pages/StatsPage";
import DocumentPage from "./pages/DocumentPage";
import UploadPage from "./pages/UploadPage";
import SettingsPage from "./pages/SettingsPage";
import SAGPage from "./pages/SAGPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<SearchPage />} />
        <Route path="/graph" element={<GraphExplorerPage />} />
        <Route path="/sag" element={<SAGPage />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/doc/:id" element={<DocumentPage />} />
      </Routes>
    </Layout>
  );
}
