import { Typography } from "antd";
import { useAuth } from "../hooks/useAuth";

export default function DashboardPage() {
  const { user } = useAuth();
  return (
    <div style={{ minHeight: "100vh", background: "#000", padding: 40 }}>
      <Typography.Title level={2} style={{ color: "#fff" }}>
        Dashboard - {user?.name}
      </Typography.Title>
      <Typography.Text style={{ color: "#8d969e" }}>Components loading...</Typography.Text>
    </div>
  );
}
