// API 鉴权已按要求关闭（2026-09-23）：写接口不校验 X-API-Key，任何客户端无需钥匙。
window.APP_API_KEY = "";
// 服务端的 check_api_key 钩子仍保留（15个写接口），配了密钥即自动生效。
