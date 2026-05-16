export function StudentAvatarGrid({ students }) {
  return (
    <div className="avatar-grid">
      {students.map((student) => (
        <div className="student-avatar" key={student.id} title={student.name}>
          {student.name.slice(0, 1)}
        </div>
      ))}
    </div>
  );
}
