import { EmptyState } from "../components/EmptyState.jsx";
import { PageHeader } from "../components/PageHeader.jsx";

export function StudentsPage() {
  return (
    <>
      <PageHeader eyebrow="תלמידים" title="תלמידים" description="בסיס למסך תלמידים עתידי." />
      <EmptyState
        title="ממשק תלמידים מוכן לחיבור"
        description="TODO: connect real students API later. כרגע השרת אינו מספק רשימת תלמידים."
      />
    </>
  );
}
