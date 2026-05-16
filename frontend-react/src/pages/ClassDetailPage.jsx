import { GroupCard } from "../components/GroupCard.jsx";
import { PageHeader } from "../components/PageHeader.jsx";
import { DataTable } from "../components/DataTable.jsx";

const mockGroups = [
  {
    name: "הקבצה א",
    subject: "מתמטיקה",
    students: [
      { id: 1, name: "נועה" },
      { id: 2, name: "דניאל" },
      { id: 3, name: "מיכל" },
      { id: 4, name: "אורי" },
      { id: 5, name: "יעל" },
    ],
  },
  {
    name: "הקבצה ב",
    subject: "אנגלית",
    students: [
      { id: 6, name: "רוני" },
      { id: 7, name: "איתן" },
      { id: 8, name: "שרה" },
      { id: 9, name: "ליה" },
    ],
  },
  {
    name: "הקבצה ג",
    subject: "גמרא",
    students: [
      { id: 10, name: "יוסף" },
      { id: 11, name: "שמואל" },
      { id: 12, name: "אליה" },
    ],
  },
];

export function ClassDetailPage({ selectedClass, data, navigate }) {
  const className = selectedClass?.name || "כיתה י״ב א";
  const columns = [
    { key: "name", label: "מקצוע" },
    { key: "hours_per_week", label: "שעות שבועיות" },
  ];

  return (
    <>
      <PageHeader
        eyebrow="כיתה"
        title={className}
        description="תצוגת עומק לכיתה, עם מקום לתלמידים, מקצועות, מורים והקבצות."
        action={<button className="secondary-button" onClick={() => navigate("classes")} type="button">חזרה לכיתות</button>}
      />
      <div className="tabs">
        {["תלמידים", "מקצועות", "מורים", "הקבצות", "מערכת"].map((tab) => (
          <button className={tab === "הקבצות" ? "active" : ""} key={tab} type="button">{tab}</button>
        ))}
      </div>
      <section className="panel">
        <div className="section-head">
          <h3>הקבצות</h3>
          <span className="muted">TODO: connect real students/groups API later.</span>
        </div>
        <div className="group-grid">
          {mockGroups.map((group) => (
            <GroupCard key={group.name} {...group} />
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="section-head">
          <h3>מקצועות בכיתה</h3>
        </div>
        <DataTable columns={columns} rows={data.subjects.slice(0, 6)} emptyText="אין מקצועות מחוברים עדיין" />
      </section>
    </>
  );
}
