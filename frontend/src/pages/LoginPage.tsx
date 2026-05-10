import { useState } from "react";
import { Form, Input, Button, Typography, App } from "antd";
import { MailOutlined, LockOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { login, getMe } from "../api/auth";
import { useAuth } from "../hooks/useAuth";
import { useTranslation } from "react-i18next";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const { t } = useTranslation();
  const { message } = App.useApp();

  const onFinish = async (values: { email: string; password: string }) => {
    setLoading(true);
    try {
      const { data } = await login(values.email, values.password);
      localStorage.setItem("token", data.access_token);
      const { data: me } = await getMe();
      setUser(me);
      navigate("/");
    } catch {
      message.error(t("login.error"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ height: "100vh", display: "flex", justifyContent: "center", alignItems: "center", background: "#000" }}>
      <div style={{ width: 360, padding: 40, background: "#16181a", borderRadius: 20 }}>
        <Typography.Title level={2} style={{ color: "#fff", textAlign: "center", marginBottom: 32 }}>
          {t("app.title")}
        </Typography.Title>
        <Form onFinish={onFinish} size="large">
          <Form.Item name="email" rules={[{ required: true }]}>
            <Input prefix={<MailOutlined />} placeholder={t("login.email")} />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true }]}>
            <Input.Password prefix={<LockOutlined />} placeholder={t("login.password")} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              {t("login.submit")}
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  );
}
