import { useEffect, useMemo, useState } from "react";
import { AppShell } from "./layout/AppShell.jsx";
import { DashboardPage } from "./pages/DashboardPage.jsx";
import { ClassesPage } from "./pages/ClassesPage.jsx";
import { ClassDetailPage } from "./pages/ClassDetailPage.jsx";
import { TeachersPage } from "./pages/TeachersPage.jsx";
import { SubjectsPage } from "./pages/SubjectsPage.jsx";
import { StudentsPage } from "./pages/StudentsPage.jsx";
import { RoomsPage } from "./pages/RoomsPage.jsx";
import { ConstraintsPage } from "./pages/ConstraintsPage.jsx";
import { SchedulePage } from "./pages/SchedulePage.jsx";
import { GenerationPage } from "./pages/GenerationPage.jsx";
import { OnboardingPage } from "./pages/OnboardingPage.jsx";
import { ImportExcelPage } from "./pages/ImportExcelPage.jsx";
import { DiagnosticPage } from "./pages/DiagnosticPage.jsx";
import { RepairPage } from "./pages/RepairPage.jsx";
import { ComparePage } from "./pages/ComparePage.jsx";
import { ExportsPage } from "./pages/ExportsPage.jsx";
import { ClassNewPage } from "./pages/ClassNewPage.jsx";
import { getClasses, getConditions, getSchedule, getSlots, getSubjects, getTeachers } from "./api/schoolApi.js";
import { getDirection, translations } from "./translations.js";

const pageMap = {
  dashboard: DashboardPage,
  onboarding: OnboardingPage,
  importExcel: ImportExcelPage,
  diagnostic: DiagnosticPage,
  repair: RepairPage,
  compare: ComparePage,
  exports: ExportsPage,
  classes: ClassesPage,
  classNew: ClassNewPage,
  classDetail: ClassDetailPage,
  teachers: TeachersPage,
  subjects: SubjectsPage,
  students: StudentsPage,
  rooms: RoomsPage,
  constraints: ConstraintsPage,
  schedule: SchedulePage,
  generation: GenerationPage,
};

const pathToPage = {
  "/": "dashboard",
  "/onboarding": "onboarding",
  "/import-excel": "importExcel",
  "/diagnostic": "diagnostic",
  "/repair": "repair",
  "/compare": "compare",
  "/exports": "exports",
  "/classes": "classes",
  "/classes/new": "classNew",
  "/generation": "generation",
  "/schedule": "schedule",
};

const pageToPath = Object.fromEntries(Object.entries(pathToPage).map(([path, page]) => [page, path]));

const initialData = {
  classes: [],
  teachers: [],
  subjects: [],
  slots: [],
  conditions: [],
  schedule: {},
};

export default function App() {
  const [activePage, setActivePage] = useState(() => pathToPage[window.location.pathname] || "dashboard");
  const [selectedClass, setSelectedClass] = useState(null);
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [language, setLanguage] = useState("he");
  const [importPreview, setImportPreview] = useState(null);
  const [activeProposal, setActiveProposal] = useState(null);

  const refreshData = async () => {
    setLoading(true);
    setError("");
    try {
      const [classes, teachers, subjects, slots, conditions, schedule] = await Promise.all([
        getClasses(),
        getTeachers(),
        getSubjects(),
        getSlots(),
        getConditions(),
        getSchedule(),
      ]);
      setData({ classes, teachers, subjects, slots, conditions, schedule });
    } catch (err) {
      setError(err.message || "טעינת הנתונים נכשלה");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshData();
  }, []);

  useEffect(() => {
    const onPopState = () => setActivePage(pathToPage[window.location.pathname] || "dashboard");
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (page, payload) => {
    if (payload?.classItem) {
      setSelectedClass(payload.classItem);
      setActivePage("classDetail");
      return;
    }
    const nextPath = pageToPath[page];
    if (nextPath && window.location.pathname !== nextPath) {
      window.history.pushState({}, "", nextPath);
    }
    setActivePage(page);
  };

  const Page = pageMap[activePage] || DashboardPage;
  const t = translations[language];
  const direction = getDirection(language);
  const pageProps = useMemo(
    () => ({
      data,
      loading,
      error,
      t,
      language,
      direction,
      selectedClass,
      importPreview,
      setImportPreview,
      activeProposal,
      setActiveProposal,
      navigate,
      refreshData,
    }),
    [data, loading, error, selectedClass, t, language, direction, importPreview, activeProposal]
  );

  return (
    <AppShell
      activePage={activePage}
      onNavigate={navigate}
      error={error}
      language={language}
      setLanguage={setLanguage}
      direction={direction}
      t={t}
    >
      <Page {...pageProps} />
    </AppShell>
  );
}
