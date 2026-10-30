/**
 * Named aliases over the generated OpenAPI types (`pnpm gen:api`). Nothing here is
 * hand-written: every shape comes from `schema.d.ts`, which is generated from
 * docs/api/openapi.yaml.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type User = S["UserOut"];
export type UserCreate = S["UserCreate"];
export type UserUpdate = S["UserUpdate"];
export type SignIn = S["SignInOut"];
export type AuditEntry = S["AuditOut"];
export type SystemInfo = S["SystemInfo"];
export type Role = NonNullable<UserCreate["role"]>;
export type PublicSettings = S["PublicSettings"];
export type AdminSettings = S["AdminSettings"];
export type SettingsUpdate = S["SettingsUpdate"];

export type Project = S["ProjectOut"];
export type ProjectCreate = S["ProjectCreate"];
export type ProjectUpdate = S["ProjectUpdate"];
export type ProjectRole = NonNullable<Project["role"]>;
export type Member = S["MemberOut"];
export type ApiKey = S["ApiKeyOut"];
export type ApiKeyCreated = S["ApiKeyCreated"];
export type Scope = NonNullable<S["ApiKeyCreate"]["scopes"]>[number];

export type Connection = S["ConnectionOut"];
export type ServerConnection = S["ServerConnection"];
export type ConnectionUpdate = S["ConnectionUpdate"];
export type ConnectionTest = S["TestResult"];
export type SourceTable = S["TableOut"];

export type Dataset = S["DatasetOut"];
export type DatasetCreate = S["DatasetCreate"];
export type DatasetUpdate = S["DatasetUpdate"];
export type DatasetFile = S["FileOut"];
export type Preview = S["PreviewOut"];
export type Profile = S["ProfileOut"];
export type ColumnProfile = S["ColumnProfileOut"];
export type Suggestion = S["SuggestionOut"];
export type MetricSeries = S["MetricSeries"];

export type Check = S["CheckOut"];
export type CheckIn = S["CheckIn"];
export type CheckUpdate = S["CheckUpdate"];
export type CheckType = S["CheckType"];
export type Dimension = S["Dimension"];
export type Severity = S["Severity"];
export type Tolerance = S["Tolerance"];
export type BulkResult = S["BulkResult"];
export type Draft = S["DraftOut"];

export type Scan = S["ScanOut"];
export type ScanDetail = S["ScanDetail"];
export type ScanPage = S["Page_ScanOut_"];
export type CheckResult = S["ResultOut"];
export type Anomaly = S["AnomalyOut"];

export type Channel = S["ChannelOut"];
export type ChannelIn = S["ChannelIn"];
export type ChannelCreated = S["ChannelCreated"];
export type Rule = S["RuleOut"];
export type RuleIn = S["RuleIn"];
export type Incident = S["IncidentOut"];
export type IncidentDetail = S["IncidentDetail"];
export type Explanation = S["ExplainOut"];

export type Dashboard = S["Dashboard"];
export type Issue = S["Issue"];
export type TrendPoint = S["TrendPoint"];
