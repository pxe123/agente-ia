# database/models.py

class Tables:
    """
    Centraliza os nomes das tabelas do Supabase para evitar erros de digitação.
    """
    CLIENTES = "clientes"
    MENSAGENS = "historico_mensagens"
    PUSH_SUBSCRIPTIONS = "painel_push_subscriptions"
    FLOWS = "flows"
    FLOW_USER_STATE = "flow_user_state"
    LEADS = "leads"
    CONTACTS = "contacts"
    CONTACT_CHANNELS = "contact_channels"
    CHATBOTS = "chatbots"
    CONVERSACAO_SETOR = "painel_conversacao_setor"
    # Sublogins e setores (usuário define setores e acesso por funcionário)
    SETORES = "setores"
    USUARIOS_INTERNOS = "usuarios_internos"
    USUARIOS_INTERNOS_SETORES = "usuarios_internos_setores"
    # Billing
    BILLING_EVENTS = "billing_events"
    SUBSCRIPTIONS = "subscriptions"
    PLANS = "plans"
    APP_SETTINGS = "app_settings"
    ADMIN_LOGS = "admin_logs"
    EGRESS_PROFILES = "egress_profiles"
    EGRESS_ASSIGNMENTS = "egress_assignments"
    # Agendamento (módulo interno)
    SCHEDULING_SETTINGS = "scheduling_settings"
    SCHEDULING_PROFESSIONALS = "scheduling_professionals"
    SCHEDULING_SERVICES = "scheduling_services"
    SCHEDULING_WORKING_HOURS = "scheduling_working_hours"
    SCHEDULING_BLOCKED_TIMES = "scheduling_blocked_times"
    SCHEDULING_APPOINTMENTS = "scheduling_appointments"
    SCHEDULING_APPOINTMENT_PROPOSALS = "scheduling_appointment_proposals"
    SCHEDULING_CONFIRMATION_TOKENS = "scheduling_confirmation_tokens"
    SCHEDULING_RECURRENCE_SERIES = "scheduling_recurrence_series"
    SCHEDULING_RECURRENCE_SKIPS = "scheduling_recurrence_skips"


class EgressProfileModel:
    """Colunas da tabela egress_profiles (proxy por tenant)."""
    ID = "id"
    NAME = "name"
    HOST = "host"
    PORT = "port"
    USERNAME = "username"
    PASSWORD = "password"
    TYPE = "type"
    COUNTRY = "country"
    IS_ACTIVE = "is_active"
    MAX_CLIENTS = "max_clients"
    LAST_TEST_IP = "last_test_ip"
    LAST_TEST_LATENCY = "last_test_latency"
    LAST_TEST_AT = "last_test_at"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class EgressAssignmentModel:
    """Colunas da tabela egress_assignments (tenant->profile)."""
    ID = "id"
    EGRESS_PROFILE_ID = "egress_profile_id"
    CLIENTE_ID = "cliente_id"
    CREATED_AT = "created_at"


class AdminLogModel:
    """Colunas da tabela admin_logs (auditoria do painel admin)."""
    ID = "id"
    ADMIN_ID = "admin_id"
    ACTION = "action"
    TARGET_ID = "target_id"
    CREATED_AT = "created_at"


class AppSettingsModel:
    """Colunas da tabela app_settings (singleton id=1)."""
    ID = "id"
    INSTAGRAM_ENABLED = "instagram_enabled"
    MESSENGER_ENABLED = "messenger_enabled"
    WHATSAPP_ENABLED = "whatsapp_enabled"
    UPDATED_AT = "updated_at"


class ClienteModel:
    """
    Representa a estrutura da tabela 'clientes'.
    Campos principais identificados no seu sistema.
    Meta (API oficial): WhatsApp Cloud, Instagram, Messenger.
    """
    ID = "id"
    AUTH_ID = "auth_id"  # auth.users.id (Supabase Auth)
    NOME = "nome"  # Opcional: adicione a coluna 'nome' (text, nullable) no Supabase se quiser armazenar o nome
    EMAIL = "email"
    SENHA = "senha"
    WHATSAPP_INSTANCIA = "whatsapp_instancia"
    PLANO = "plano"
    # Billing / entitlement (Mercado Pago)
    BILLING_PLAN_KEY = "billing_plan_key"
    BILLING_STATUS = "billing_status"  # active | trialing | pending | past_due | canceled | inactive
    BILLING_CURRENT_PERIOD_END = "billing_current_period_end"  # timestamp/iso
    TRIAL_ENDS_AT = "trial_ends_at"
    MP_CUSTOMER_ID = "mp_customer_id"
    MP_PREAPPROVAL_ID = "mp_preapproval_id"
    BILLING_PENDING_PLAN_KEY = "billing_pending_plan_key"
    BILLING_PENDING_PLAN_CHANGE_AT = "billing_pending_plan_change_at"
    BILLING_PENDING_PLAN_CHANGE_TYPE = "billing_pending_plan_change_type"
    # Cancelamento (fim do período)
    BILLING_CANCEL_AT_PERIOD_END = "billing_cancel_at_period_end"
    BILLING_CANCEL_SCHEDULED_AT = "billing_cancel_scheduled_at"
    NOTIFY_WHATSAPP = "notify_whatsapp"
    # API oficial Meta - WhatsApp Cloud
    META_WA_PHONE_NUMBER_ID = "meta_wa_phone_number_id"
    META_WA_TOKEN = "meta_wa_token"
    META_WA_WABA_ID = "meta_wa_waba_id"
    # Instagram Messaging (page_id = Facebook Page ID para envio; account_id = Instagram Business Account ID no webhook)
    META_IG_PAGE_ID = "meta_ig_page_id"
    META_IG_ACCOUNT_ID = "meta_ig_account_id"
    META_IG_TOKEN = "meta_ig_token"
    # Facebook Messenger
    META_FB_PAGE_ID = "meta_fb_page_id"
    META_FB_TOKEN = "meta_fb_token"
    # Chat para site (widget instalável); coluna canónica embed_key (UNIQUE). WEBSITE_CHAT_EMBED_KEY aponta para a mesma coluna.
    EMBED_KEY = "embed_key"
    WEBSITE_CHAT_EMBED_KEY = "embed_key"
    # Controle de acesso (admin pode habilitar/desabilitar por canal)
    ACESSO_WHATSAPP = "acesso_whatsapp"
    ACESSO_INSTAGRAM = "acesso_instagram"
    ACESSO_MESSENGER = "acesso_messenger"
    ACESSO_SITE = "acesso_site"
    # Data de criação da conta (Supabase pode usar created_at)
    CRIADO_EM = "created_at"

    # Onboarding funnel (v2)
    SIGNUP_FLOW_VERSION = "signup_flow_version"  # 1=legacy, 2=onboarding funnel
    ONBOARDING_COMPLETED_AT = "onboarding_completed_at"
    ACTIVATED_AT = "activated_at"


class BillingEventModel:
    """Colunas da tabela billing_events (idempotência e auditoria de webhooks)."""
    EVENT_ID = "event_id"  # pode ser data.id + type ou id do evento (quando existir)
    REQUEST_ID = "request_id"
    RESOURCE_TYPE = "resource_type"  # payment | preapproval | subscription_preapproval | etc
    DATA_ID = "data_id"
    CLIENTE_ID = "cliente_id"
    RAW_BODY = "raw_body"
    RECEIVED_AT = "received_at"
    PROCESSED_AT = "processed_at"
    STATUS = "status"  # received | processed | ignored | failed
    # Enriquecimento (fonte Mercado Pago)
    MP_STATUS = "mp_status"
    PLAN_KEY = "plan_key"
    NEXT_PAYMENT_DATE = "next_payment_date"
    AMOUNT = "amount"
    CURRENCY = "currency"


class SubscriptionModel:
    """Colunas da tabela subscriptions (histórico/auditoria; opcional)."""
    ID = "id"
    CLIENTE_ID = "cliente_id"
    USER_ID = "user_id"
    PROVIDER = "provider"  # mercadopago
    PROVIDER_SUBSCRIPTION_ID = "provider_subscription_id"  # preapproval_id
    PLAN_KEY = "plan_key"
    STATUS = "status"
    CURRENT_PERIOD_END = "current_period_end"
    TRIAL_ENDS_AT = "trial_ends_at"
    STRIPE_CUSTOMER_ID = "stripe_customer_id"
    STRIPE_SUBSCRIPTION_ID = "stripe_subscription_id"
    STRIPE_PRICE_ID = "stripe_price_id"
    CANCEL_AT_PERIOD_END = "cancel_at_period_end"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class PlanModel:
    """Colunas da tabela plans (fonte de verdade de preços, trial e entitlements)."""
    PLAN_KEY = "plan_key"
    NAME = "name"
    PRICE = "price"
    CURRENCY = "currency"
    TRIAL_DAYS = "trial_days"
    ACTIVE = "active"
    ENTITLEMENTS_JSON = "entitlements_json"
    IS_PRIVATE = "is_private"
    PRIVATE_CLIENTE_ID = "private_cliente_id"
    STRIPE_PRICE_ID = "stripe_price_id"
    STRIPE_PRODUCT_ID = "stripe_product_id"

class MensagemModel:
    """
    Representa a estrutura da tabela 'historico_mensagens'.
    Esta tabela é o coração do seu 'tratamento de informação'.
    Campos anexo_*: opcionais; adicione as colunas no Supabase se quiser download de imagens/arquivos.
    atendente_*: quem atendeu (chatbot ou humano) para exibir no painel e ao cliente final.
    """
    ID = "id"
    CLIENTE_ID = "cliente_id"  # FK para Clientes
    REMOTE_ID = "remote_id"    # ID do utilizador final (ex: número do WhatsApp)
    CANAL = "canal"            # 'whatsapp', 'instagram', 'facebook', 'website'
    FUNCAO = "funcao"          # 'user' ou 'assistant'
    CONTEUDO = "conteudo"      # O texto da mensagem
    CRIADO_EM = "created_at"   # Timestamp automático do banco
    # Anexos (imagem/arquivo): adicione colunas anexo_url, anexo_nome, anexo_tipo na tabela se quiser usar
    ANEXO_URL = "anexo_url"    # ex: /api/anexo/clienteid_uuid.jpg
    ANEXO_NOME = "anexo_nome"  # nome original (ex: foto.jpg, documento.pdf)
    ANEXO_TIPO = "anexo_tipo"  # MIME (ex: image/jpeg, application/pdf)
    # Atendente (quem enviou: chatbot ou humano) — exibido no painel e nas redes
    ATENDENTE_TIPO = "atendente_tipo"            # 'chatbot' | 'humano'
    ATENDENTE_USUARIO_ID = "atendente_usuario_id"  # FK usuarios_internos.id quando tipo=humano
    ATENDENTE_NOME_SNAPSHOT = "atendente_nome_snapshot"  # nome no momento do envio (ex: "Amanda", "Chatbot Vendas")


class FlowModel:
    """Colunas da tabela flows (Flow Builder)."""
    ID = "id"
    CLIENTE_ID = "cliente_id"
    CHANNEL = "channel"  # default, welcome, whatsapp, instagram, messenger, website
    CHATBOT_ID = "chatbot_id"  # se preenchido, fluxo pertence ao chatbot
    NAME = "name"
    FLOW_JSON = "flow_json"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class FlowUserStateModel:
    """Colunas da tabela flow_user_state."""
    CLIENTE_ID = "cliente_id"
    CANAL = "canal"
    REMOTE_ID = "remote_id"
    CONTACT_ID = "contact_id"
    FLOW_ID = "flow_id"
    CURRENT_NODE_ID = "current_node_id"
    COLLECTED_DATA = "collected_data"
    UPDATED_AT = "updated_at"


class LeadModel:
    """Colunas da tabela leads (captura no fluxo)."""
    ID = "id"
    CLIENTE_ID = "cliente_id"
    CANAL = "canal"
    REMOTE_ID = "remote_id"
    CONTACT_ID = "contact_id"
    FLOW_ID = "flow_id"
    NOME = "nome"
    EMAIL = "email"
    TELEFONE = "telefone"
    DADOS = "dados"
    STATUS = "status"  # pendente | qualificado | desqualificado
    CREATED_AT = "created_at"


class ChatbotModel:
    """Colunas da tabela chatbots (Meus Chatbots)."""
    ID = "id"
    CLIENTE_ID = "cliente_id"
    NOME = "nome"
    DESCRICAO = "descricao"
    CHANNELS = "channels"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SetorModel:
    """Colunas da tabela setores (áreas de atuação definidas pelo cliente)."""
    ID = "id"
    CLIENTE_ID = "cliente_id"
    NOME = "nome"
    ATIVO = "ativo"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class UsuarioInternoModel:
    """Colunas da tabela usuarios_internos (sublogins / funcionários)."""
    ID = "id"
    CLIENTE_ID = "cliente_id"
    NOME = "nome"
    EMAIL_LOGIN = "email_login"
    SENHA = "senha"
    ATIVO = "ativo"
    IS_ADMIN_CLIENTE = "is_admin_cliente"
    ACESSO_MENUS = "acesso_menus"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class UsuarioInternoSetorModel:
    """Colunas da tabela usuarios_internos_setores (acesso do funcionário a setores)."""
    ID = "id"
    USUARIO_INTERNO_ID = "usuario_interno_id"
    SETOR_ID = "setor_id"


class ConversacaoSetorModel:
    """Colunas da tabela painel_conversacao_setor (estado + responsável + setor de negócio)."""
    CLIENTE_ID = "cliente_id"
    CANAL = "canal"
    REMOTE_ID = "remote_id"
    SETOR = "setor"  # atendimento_ia | atendimento_humano | atendimento_encerrado
    SETOR_ID = "setor_id"  # FK setores.id (área de negócio: Vendas, Suporte, etc.)
    RESPONSAVEL_USUARIO_ID = "responsavel_usuario_id"  # FK usuarios_internos.id
    RESPONSAVEL_NOME_SNAPSHOT = "responsavel_nome_snapshot"
    UPDATED_AT = "updated_at"


class SchedulingSettingsModel:
    CLIENTE_ID = "cliente_id"
    TIMEZONE = "timezone"
    PUBLIC_NAME = "public_name"
    PUBLIC_SLUG = "public_slug"
    SCHEDULING_ENGINE = "scheduling_engine"
    SCHEDULING_ENGINE_CHANGED_AT = "scheduling_engine_changed_at"
    SCHEDULING_ENGINE_CHANGED_BY = "scheduling_engine_changed_by"
    PROFESSIONAL_ASSIGNMENT_MODE = "professional_assignment_mode"
    DISTRIBUTION_STRATEGY = "distribution_strategy"
    DISTRIBUTION_LAST_PROFESSIONAL_ID = "distribution_last_professional_id"
    ASSIGNMENT_MODE_CHANGED_AT = "assignment_mode_changed_at"
    ASSIGNMENT_MODE_CHANGED_BY = "assignment_mode_changed_by"
    CONFIRMATION_POLICY = "confirmation_policy"
    CONFIRMATION_PENDING_TTL_HOURS = "confirmation_pending_ttl_hours"
    CONFIRMATION_POLICY_CHANGED_AT = "confirmation_policy_changed_at"
    CONFIRMATION_POLICY_CHANGED_BY = "confirmation_policy_changed_by"
    WORKING_HOUR_CONFIG = "working_hour_config"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SchedulingProfessionalModel:
    ID = "id"
    CLIENTE_ID = "cliente_id"
    NAME = "name"
    ACTIVE = "active"
    SORT_ORDER = "sort_order"
    WHATSAPP_NOTIFY_PHONE = "whatsapp_notify_phone"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SchedulingAppointmentProposalModel:
    ID = "id"
    APPOINTMENT_ID = "appointment_id"
    CLIENTE_ID = "cliente_id"
    PROPOSED_STARTS_AT = "proposed_starts_at"
    PROPOSED_ENDS_AT = "proposed_ends_at"
    PROPOSED_BY = "proposed_by"
    STATUS = "status"
    CREATED_AT = "created_at"


class SchedulingConfirmationTokenModel:
    ID = "id"
    TOKEN_HASH = "token_hash"
    APPOINTMENT_ID = "appointment_id"
    PROPOSAL_ID = "proposal_id"
    CLIENTE_ID = "cliente_id"
    ACTION = "action"
    EXPIRES_AT = "expires_at"
    USED_AT = "used_at"
    CREATED_AT = "created_at"


class SchedulingServiceModel:
    ID = "id"
    CLIENTE_ID = "cliente_id"
    NAME = "name"
    DURATION_MINUTES = "duration_minutes"
    PRICE_CENTS = "price_cents"
    PROFESSIONAL_ID = "professional_id"
    ACTIVE = "active"
    SORT_ORDER = "sort_order"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SchedulingWorkingHoursModel:
    ID = "id"
    CLIENTE_ID = "cliente_id"
    PROFESSIONAL_ID = "professional_id"
    DAY_OF_WEEK = "day_of_week"
    START_TIME = "start_time"
    END_TIME = "end_time"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SchedulingBlockedTimeModel:
    ID = "id"
    CLIENTE_ID = "cliente_id"
    PROFESSIONAL_ID = "professional_id"
    STARTS_AT = "starts_at"
    ENDS_AT = "ends_at"
    REASON = "reason"
    CREATED_AT = "created_at"


class SchedulingRecurrenceSeriesModel:
    ID = "id"
    CLIENTE_ID = "cliente_id"
    SERVICE_ID = "service_id"
    PROFESSIONAL_ID = "professional_id"
    STATUS = "status"
    FREQUENCY = "frequency"
    RULE = "rule"
    TIME_LOCAL = "time_local"
    STARTS_ON = "starts_on"
    ENDS_ON = "ends_on"
    CONTACT_NAME = "contact_name"
    CONTACT_PHONE = "contact_phone"
    NOTES = "notes"
    META = "meta"
    MATERIALIZED_UNTIL = "materialized_until"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SchedulingRecurrenceSkipModel:
    ID = "id"
    CLIENTE_ID = "cliente_id"
    SERIES_ID = "series_id"
    OCCURRENCE_DATE = "occurrence_date"
    CREATED_AT = "created_at"


class SchedulingAppointmentModel:
    ID = "id"
    CLIENTE_ID = "cliente_id"
    EXTERNAL_AGENDA_APPOINTMENT_ID = "external_agenda_appointment_id"
    SERVICE_ID = "service_id"
    PROFESSIONAL_ID = "professional_id"
    STARTS_AT = "starts_at"
    ENDS_AT = "ends_at"
    STATUS = "status"
    REMOTE_ID = "remote_id"
    CONTACT_PHONE = "contact_phone"
    NOTES = "notes"
    META = "meta"
    RECURRENCE_SERIES_ID = "recurrence_series_id"
    SERIES_OCCURRENCE_AT = "series_occurrence_at"
    IS_SERIES_EXCEPTION = "is_series_exception"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"

