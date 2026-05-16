import { StudentAvatarGrid } from "./StudentAvatarGrid.jsx";

export function GroupCard({ name, subject, students }) {
  return (
    <article className="group-card">
      <div className="group-card-head">
        <div>
          <h3>{name}</h3>
          <span>{subject}</span>
        </div>
        <strong>{students.length}</strong>
      </div>
      <StudentAvatarGrid students={students} />
    </article>
  );
}
