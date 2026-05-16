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
import { getClasses, getConditions, getSchedule, getSlots, getSubjects, getTeachers } from "./api/schoolApi.js";

const pageMap = {
  dashboard: DashboardPage,
  classes: ClassesPage,
  classDetail: ClassDetailPage,
  teachers: TeachersPage,
  subjects: SubjectsPage,
  students: StudentsPage,
  rooms: RoomsPage,
  constraints: ConstraintsPage,
  schedule: SchedulePage,
  generation: GenerationPage,
};

const initialData = {
  classes: [],
  teachers: [],
  subjects: [],
  slots: [],
  conditions: [],
  schedule: {},
};

export default function App() {
  const [activePage, setActivePage] = useState("dashboard");
  const [selectedClass, setSelectedClass] = useState(null);
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

  const navigate = (page, payload) => {
    if (payload?.classItem) {
      setSelectedClass(payload.classItem);
      setActivePage("classDetail");
      return;
    }
    setActivePage(page);
  };

  const Page = pageMap[activePage] || DashboardPage;
  const pageProps = useMemo(
    () => ({
      data,
      loading,
      error,
      selectedClass,
      navigate,
      refreshData,
    }),
    [data, loading, error, selectedClass]
  );

  return (
    <AppShell activePage={activePage} onNavigate={navigate} error={error}>
      <Page {...pageProps} />
    </AppShell>
  );
}
