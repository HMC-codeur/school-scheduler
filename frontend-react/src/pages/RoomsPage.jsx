import { PageHeader } from "../components/PageHeader.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

// TODO: connect real rooms API later. The current backend does not expose rooms.
const mockRooms = [
  { id: 1, name: "חדר 101", type: "כיתה רגילה", capacity: 32, available: true },
  { id: 2, name: "בית מדרש מרכזי", type: "בית מדרש", capacity: 90, available: true },
  { id: 3, name: "מעבדה 2", type: "מעבדה", capacity: 24, available: false },
  { id: 4, name: "מחשבים א", type: "מחשבים", capacity: 28, available: true },
  { id: 5, name: "חדר לימוד קטן", type: "חדר לימוד", capacity: 12, available: true },
];

export function RoomsPage() {
  return (
    <>
      <PageHeader
        eyebrow="משאבים"
        title="חדרים"
        description="ממשק ניהול חדרים ראשוני, מוכן לחיבור API עתידי."
        action={<button className="secondary-button" type="button">הוסף חדר</button>}
      />
      <div className="room-grid">
        {mockRooms.map((room) => (
          <article className="room-card" key={room.id}>
            <div>
              <h3>{room.name}</h3>
              <p>{room.type}</p>
            </div>
            <div className="room-meta">
              <span>קיבולת {room.capacity}</span>
              <StatusBadge status={room.available ? "ready" : "danger"}>
                {room.available ? "זמין" : "לא זמין"}
              </StatusBadge>
            </div>
          </article>
        ))}
      </div>
      <p className="todo-note">TODO: connect real rooms API later.</p>
    </>
  );
}
