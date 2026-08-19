import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Edit3, Layers3, Plus, Power } from 'lucide-react';
import { supabase } from '../lib/supabase';
import {
  PlatformAccount,
  Profile,
  ProfileDestination,
  ProfileRenderSettings,
  ProfileSource,
} from '../types';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import { Switch } from '../components/ui/Switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/Table';

type PublicationMode = ProfileDestination['publication_mode'];

type ProfileForm = {
  profile_id: string;
  name: string;
  description: string;
  niche: string;
  editorial_strategy: string;
  language: string;
  enabled: boolean;
  source_type: string;
  source_ref: string;
  aspect_ratio: ProfileRenderSettings['aspect_ratio'];
  layout: ProfileRenderSettings['layout'];
  min_duration_seconds: number;
  max_duration_seconds: number;
  target_height: number;
  captions_enabled: boolean;
  headline_enabled: boolean;
  brand: string;
  cta: string;
  destination_account_ids: string[];
  publication_mode: PublicationMode;
  max_posts_per_day: number;
  minimum_interval_seconds: number;
  allowed_hours: string;
  timezone: string;
  max_pending_jobs: number;
  max_attempts: number;
};

const EMPTY_FORM: ProfileForm = {
  profile_id: '',
  name: '',
  description: '',
  niche: '',
  editorial_strategy: 'default',
  language: 'pt-BR',
  enabled: false,
  source_type: 'twitch',
  source_ref: '',
  aspect_ratio: '9:16',
  layout: 'vertical-fit',
  min_duration_seconds: 5,
  max_duration_seconds: 60,
  target_height: 720,
  captions_enabled: true,
  headline_enabled: true,
  brand: '',
  cta: '',
  destination_account_ids: [],
  publication_mode: 'disabled',
  max_posts_per_day: 0,
  minimum_interval_seconds: 0,
  allowed_hours: '',
  timezone: 'UTC',
  max_pending_jobs: 0,
  max_attempts: 3,
};

function relationOne<T>(value: T | T[] | null | undefined): T | null {
  return Array.isArray(value) ? value[0] ?? null : value ?? null;
}

function normalizeProfile(raw: Record<string, unknown>): Profile {
  const render = relationOne(raw.profile_render_settings as ProfileRenderSettings | ProfileRenderSettings[]);
  const destinations = ((raw.profile_destinations as ProfileDestination[]) || []).map((destination) => ({
    ...destination,
    platform_accounts: relationOne(
      destination.platform_accounts as PlatformAccount | PlatformAccount[] | null,
    ),
  }));
  return {
    ...(raw as unknown as Profile),
    profile_sources: (raw.profile_sources as ProfileSource[]) || [],
    profile_destinations: destinations,
    profile_render_settings: render,
  };
}

function profileToForm(profile: Profile): ProfileForm {
  const render = profile.profile_render_settings;
  const source = profile.profile_sources[0];
  const enabledDestinations = profile.profile_destinations.filter((destination) => destination.enabled);
  const representative = enabledDestinations[0] || profile.profile_destinations[0];
  return {
    profile_id: profile.profile_id,
    name: profile.name,
    description: profile.description || '',
    niche: profile.niche || '',
    editorial_strategy: profile.editorial_strategy,
    language: profile.language,
    enabled: profile.enabled,
    source_type: source?.source_type || 'twitch',
    source_ref: source?.source_ref || '',
    aspect_ratio: render?.aspect_ratio || '9:16',
    layout: render?.layout || 'vertical-fit',
    min_duration_seconds: render?.min_duration_seconds ?? 5,
    max_duration_seconds: render?.max_duration_seconds ?? 60,
    target_height: render?.target_height ?? 720,
    captions_enabled: render?.captions_enabled ?? true,
    headline_enabled: render?.headline_enabled ?? true,
    brand: render?.brand || '',
    cta: render?.cta || '',
    destination_account_ids: profile.profile_destinations
      .map((destination) => destination.account_id)
      .filter((id): id is string => Boolean(id)),
    publication_mode: representative?.publication_mode || 'disabled',
    max_posts_per_day: representative?.max_posts_per_day ?? 0,
    minimum_interval_seconds: representative?.minimum_interval_seconds ?? 0,
    allowed_hours: (representative?.allowed_hours || []).join(','),
    timezone: representative?.timezone || 'UTC',
    max_pending_jobs: representative?.max_pending_jobs ?? 0,
    max_attempts: representative?.max_attempts ?? 3,
  };
}

function configurationStatus(profile: Profile): { label: string; ok: boolean } {
  if (!profile.profile_render_settings) return { label: 'Render pendente', ok: false };
  if (profile.profile_sources.length === 0) return { label: 'Fonte pendente', ok: false };
  if (profile.profile_destinations.length === 0) return { label: 'Destino pendente', ok: false };
  return { label: 'Configurado', ok: true };
}

export function Perfis() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<ProfileForm>(EMPTY_FORM);

  const loadData = useCallback(async () => {
    if (!supabase) {
      setError('Supabase não configurado.');
      setLoading(false);
      return;
    }
    setError(null);
    try {
      const [profileResult, accountResult] = await Promise.all([
        supabase
          .from('profiles')
          .select(`
            *,
            profile_sources(*),
            profile_destinations(*, platform_accounts(id, platform, account_key, display_name, status)),
            profile_render_settings(*)
          `)
          .order('profile_id'),
        supabase
          .from('platform_accounts')
          .select('id, platform, account_key, display_name, status')
          .order('platform')
          .order('account_key'),
      ]);
      if (profileResult.error) throw profileResult.error;
      if (accountResult.error) throw accountResult.error;
      setProfiles((profileResult.data || []).map((row) => normalizeProfile(row)));
      setAccounts((accountResult.data || []) as PlatformAccount[]);
    } catch (err) {
      console.error(err);
      setError(
        'Não foi possível carregar os perfis. Confirme se a migration multi-perfil foi aplicada no Supabase.',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const resetEditor = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const startCreate = () => {
    setEditingId('');
    setForm(EMPTY_FORM);
  };

  const startEdit = (profile: Profile) => {
    setEditingId(profile.profile_id);
    setForm(profileToForm(profile));
  };

  const selectedAccounts = useMemo(
    () => accounts.filter((account) => form.destination_account_ids.includes(account.id)),
    [accounts, form.destination_account_ids],
  );

  const toggleAccount = (accountId: string) => {
    setForm((current) => ({
      ...current,
      destination_account_ids: current.destination_account_ids.includes(accountId)
        ? current.destination_account_ids.filter((id) => id !== accountId)
        : [...current.destination_account_ids, accountId],
    }));
  };

  const saveProfile = async (event: FormEvent) => {
    event.preventDefault();
    if (!supabase || !form.profile_id.trim() || !form.name.trim()) return;
    if (form.min_duration_seconds > form.max_duration_seconds) {
      setError('A duração mínima não pode ser maior que a duração máxima.');
      return;
    }
    setSaving(true);
    setError(null);
    const profileId = form.profile_id.trim().toLowerCase();
    const isNew = editingId === '';
    try {
      const profilePayload = {
        profile_id: profileId,
        name: form.name.trim(),
        description: form.description.trim() || null,
        niche: form.niche.trim() || null,
        editorial_strategy: form.editorial_strategy.trim() || 'default',
        language: form.language.trim() || 'pt-BR',
        enabled: form.enabled,
      };
      const profileResult = isNew
        ? await supabase.from('profiles').insert(profilePayload)
        : await supabase.from('profiles').update(profilePayload).eq('profile_id', editingId);
      if (profileResult.error) throw profileResult.error;

      const renderResult = await supabase.from('profile_render_settings').upsert({
        profile_id: profileId,
        aspect_ratio: form.aspect_ratio,
        layout: form.layout,
        min_duration_seconds: form.min_duration_seconds,
        max_duration_seconds: form.max_duration_seconds,
        target_height: form.target_height || null,
        captions_enabled: form.captions_enabled,
        headline_enabled: form.headline_enabled,
        brand: form.brand.trim() || null,
        cta: form.cta.trim() || null,
      });
      if (renderResult.error) throw renderResult.error;

      const deleteSources = await supabase.from('profile_sources').delete().eq('profile_id', profileId);
      if (deleteSources.error) throw deleteSources.error;
      if (form.source_ref.trim()) {
        const sourceResult = await supabase.from('profile_sources').insert({
          profile_id: profileId,
          source_type: form.source_type.trim(),
          source_ref: form.source_ref.trim(),
          enabled: true,
        });
        if (sourceResult.error) throw sourceResult.error;
      }

      const deleteDestinations = await supabase
        .from('profile_destinations')
        .delete()
        .eq('profile_id', profileId);
      if (deleteDestinations.error) throw deleteDestinations.error;
      if (selectedAccounts.length > 0) {
        const destinationResult = await supabase.from('profile_destinations').insert(
          selectedAccounts.map((account) => ({
            profile_id: profileId,
            platform: account.platform,
            account_id: account.id,
            enabled: form.publication_mode !== 'disabled',
            publication_mode: form.publication_mode,
            max_posts_per_day: form.max_posts_per_day || null,
            minimum_interval_seconds: form.minimum_interval_seconds,
            allowed_hours: form.allowed_hours
              .split(',')
              .map((hour) => Number(hour.trim()))
              .filter((hour) => Number.isInteger(hour) && hour >= 0 && hour <= 23),
            timezone: form.timezone.trim() || 'UTC',
            max_pending_jobs: form.max_pending_jobs || null,
            max_attempts: form.max_attempts,
          })),
        );
        if (destinationResult.error) throw destinationResult.error;
      }

      resetEditor();
      await loadData();
    } catch (err) {
      console.error(err);
      if (isNew) {
        await supabase.from('profiles').delete().eq('profile_id', profileId);
      }
      setError('Não foi possível salvar o perfil. Nenhum secret foi enviado ao frontend.');
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (profile: Profile) => {
    if (!supabase) return;
    const { error: updateError } = await supabase
      .from('profiles')
      .update({ enabled: !profile.enabled })
      .eq('profile_id', profile.profile_id);
    if (updateError) {
      setError('Não foi possível alterar o status do perfil.');
      return;
    }
    await loadData();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Perfis</h2>
          <p className="text-zinc-400">
            Configurações editoriais, fontes, renderização e destinos do BotLive.
          </p>
        </div>
        <Button onClick={startCreate}>
          <Plus className="mr-2 h-4 w-4" />
          Novo perfil
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Perfis cadastrados</CardDescription>
            <CardTitle className="text-3xl">{profiles.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Perfis ativos</CardDescription>
            <CardTitle className="text-3xl">{profiles.filter((profile) => profile.enabled).length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Produção e publicação</CardDescription>
            <CardTitle className="text-base text-zinc-400">Métricas ainda indisponíveis</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-zinc-500">
            A interface está preparada para fila, produzidos, pendentes, publicados e erros quando o backend existir.
          </CardContent>
        </Card>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-900/60 bg-red-950/30 p-3 text-sm text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {editingId !== null && (
        <Card>
          <CardHeader>
            <CardTitle>{editingId ? `Editar ${editingId}` : 'Novo perfil'}</CardTitle>
            <CardDescription>
              Somente referências de conta são exibidas. Tokens, senhas e secrets não fazem parte deste formulário.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={saveProfile} className="space-y-6">
              <section className="space-y-3">
                <h3 className="font-semibold">Geral e editorial</h3>
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                  <Field label="Profile ID">
                    <Input
                      value={form.profile_id}
                      disabled={Boolean(editingId)}
                      pattern="[a-z0-9][a-z0-9_-]{1,62}"
                      onChange={(event) => setForm({ ...form, profile_id: event.target.value.toLowerCase() })}
                      required
                    />
                  </Field>
                  <Field label="Nome">
                    <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required />
                  </Field>
                  <Field label="Nicho">
                    <Input value={form.niche} onChange={(event) => setForm({ ...form, niche: event.target.value })} placeholder="Ex.: gta, football" />
                  </Field>
                  <Field label="Estratégia editorial">
                    <Input value={form.editorial_strategy} onChange={(event) => setForm({ ...form, editorial_strategy: event.target.value })} required />
                  </Field>
                  <Field label="Idioma">
                    <Input value={form.language} onChange={(event) => setForm({ ...form, language: event.target.value })} required />
                  </Field>
                  <Field label="Descrição">
                    <Input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
                  </Field>
                </div>
              </section>

              <section className="space-y-3">
                <h3 className="font-semibold">Fonte</h3>
                <div className="grid gap-4 md:grid-cols-2">
                  <Field label="Tipo">
                    <Input value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value })} />
                  </Field>
                  <Field label="Canal, URL ou referência">
                    <Input value={form.source_ref} onChange={(event) => setForm({ ...form, source_ref: event.target.value })} />
                  </Field>
                </div>
              </section>

              <section className="space-y-3">
                <h3 className="font-semibold">Renderização</h3>
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                  <SelectField
                    label="Formato"
                    value={form.aspect_ratio}
                    options={['9:16', 'original']}
                    onChange={(value) => setForm({ ...form, aspect_ratio: value as ProfileForm['aspect_ratio'] })}
                  />
                  <SelectField
                    label="Layout"
                    value={form.layout}
                    options={['vertical-fit', 'vertical-crop', 'original']}
                    onChange={(value) => setForm({ ...form, layout: value as ProfileForm['layout'] })}
                  />
                  <NumberField label="Duração mínima" value={form.min_duration_seconds} min={0} onChange={(value) => setForm({ ...form, min_duration_seconds: value })} />
                  <NumberField label="Duração máxima" value={form.max_duration_seconds} min={1} onChange={(value) => setForm({ ...form, max_duration_seconds: value })} />
                  <NumberField label="Altura alvo" value={form.target_height} min={1} onChange={(value) => setForm({ ...form, target_height: value })} />
                  <Field label="Marca">
                    <Input value={form.brand} onChange={(event) => setForm({ ...form, brand: event.target.value })} />
                  </Field>
                  <Field label="CTA">
                    <Input value={form.cta} onChange={(event) => setForm({ ...form, cta: event.target.value })} />
                  </Field>
                  <div className="flex items-end gap-4 pb-2">
                    <Toggle label="Legendas" checked={form.captions_enabled} onChange={(checked) => setForm({ ...form, captions_enabled: checked })} />
                    <Toggle label="Headline" checked={form.headline_enabled} onChange={(checked) => setForm({ ...form, headline_enabled: checked })} />
                  </div>
                </div>
              </section>

              <section className="space-y-3">
                <h3 className="font-semibold">Destinos e publicação</h3>
                {accounts.length === 0 ? (
                  <p className="text-sm text-zinc-500">
                    Nenhuma conta cadastrada no backend. Cadastre uma referência em platform_accounts; não insira secrets.
                  </p>
                ) : (
                  <div className="grid gap-2 md:grid-cols-2">
                    {accounts.map((account) => (
                      <label key={account.id} className="flex cursor-pointer items-center justify-between rounded-lg border border-zinc-800 p-3">
                        <span>
                          <span className="font-medium capitalize">{account.platform}</span>
                          <span className="ml-2 text-sm text-zinc-400">{account.display_name || account.account_key}</span>
                        </span>
                        <input
                          type="checkbox"
                          checked={form.destination_account_ids.includes(account.id)}
                          onChange={() => toggleAccount(account.id)}
                          className="h-4 w-4"
                        />
                      </label>
                    ))}
                  </div>
                )}
                <div className="grid gap-4 md:grid-cols-2">
                  <SelectField
                    label="Modo de publicação"
                    value={form.publication_mode}
                    options={['disabled', 'manual', 'approval', 'prepare_only', 'automatic']}
                    onChange={(value) => setForm({ ...form, publication_mode: value as PublicationMode })}
                  />
                  <NumberField label="Máximo por dia" value={form.max_posts_per_day} min={0} onChange={(value) => setForm({ ...form, max_posts_per_day: value })} />
                  <NumberField label="Intervalo mínimo (s)" value={form.minimum_interval_seconds} min={0} onChange={(value) => setForm({ ...form, minimum_interval_seconds: value })} />
                  <NumberField label="Máximo pendentes" value={form.max_pending_jobs} min={0} onChange={(value) => setForm({ ...form, max_pending_jobs: value })} />
                  <NumberField label="Máximo tentativas" value={form.max_attempts} min={1} onChange={(value) => setForm({ ...form, max_attempts: value })} />
                  <Field label="Horários permitidos (0–23)">
                    <Input value={form.allowed_hours} onChange={(event) => setForm({ ...form, allowed_hours: event.target.value })} placeholder="Ex.: 9,12,18,21" />
                  </Field>
                  <Field label="Timezone">
                    <Input value={form.timezone} onChange={(event) => setForm({ ...form, timezone: event.target.value })} placeholder="America/Sao_Paulo" />
                  </Field>
                </div>
              </section>

              <div className="flex items-center justify-between border-t border-zinc-800 pt-4">
                <Toggle label="Perfil ativo" checked={form.enabled} onChange={(checked) => setForm({ ...form, enabled: checked })} />
                <div className="flex gap-2">
                  <Button type="button" variant="outline" onClick={resetEditor}>Cancelar</Button>
                  <Button type="submit" disabled={saving}>{saving ? 'Salvando...' : 'Salvar perfil'}</Button>
                </div>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Perfil</TableHead>
              <TableHead>Editorial</TableHead>
              <TableHead>Fonte</TableHead>
              <TableHead>Destinos</TableHead>
              <TableHead>Render</TableHead>
              <TableHead>Configuração</TableHead>
              <TableHead className="text-right">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={7} className="py-10 text-center text-zinc-400">Carregando...</TableCell></TableRow>
            ) : profiles.length === 0 ? (
              <TableRow><TableCell colSpan={7} className="py-10 text-center text-zinc-400">Nenhum perfil cadastrado.</TableCell></TableRow>
            ) : profiles.map((profile) => {
              const status = configurationStatus(profile);
              const render = profile.profile_render_settings;
              return (
                <TableRow key={profile.profile_id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Layers3 className="h-4 w-4 text-zinc-500" />
                      <div>
                        <div className="font-medium">{profile.name}</div>
                        <code className="text-xs text-zinc-500">{profile.profile_id}</code>
                      </div>
                    </div>
                    <Badge variant={profile.enabled ? 'success' : 'secondary'} className="mt-2">
                      {profile.enabled ? 'Ativo' : 'Inativo'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div>{profile.niche || 'Sem nicho'}</div>
                    <div className="text-xs text-zinc-500">{profile.editorial_strategy}</div>
                  </TableCell>
                  <TableCell className="max-w-44">
                    {profile.profile_sources.length === 0 ? '—' : profile.profile_sources.map((source) => (
                      <div key={source.id} className="truncate text-sm">
                        <span className="text-zinc-500">{source.source_type}:</span> {source.source_ref}
                      </div>
                    ))}
                  </TableCell>
                  <TableCell>
                    {profile.profile_destinations.length === 0 ? '—' : profile.profile_destinations.map((destination) => (
                      <div key={destination.id} className="mb-1 text-sm">
                        <span className="capitalize">{destination.platform}</span>
                        <span className="text-zinc-500"> · {destination.platform_accounts?.display_name || destination.platform_accounts?.account_key || 'sem conta'}</span>
                        <div className="text-xs text-zinc-500">
                          {destination.publication_mode === 'prepare_only'
                            ? 'Prepare Only'
                            : destination.publication_mode}
                        </div>
                      </div>
                    ))}
                  </TableCell>
                  <TableCell>
                    {render ? (
                      <>
                        <div>{render.aspect_ratio} · {render.layout}</div>
                        <div className="text-xs text-zinc-500">
                          {render.min_duration_seconds}s–{render.max_duration_seconds}s
                        </div>
                      </>
                    ) : '—'}
                  </TableCell>
                  <TableCell>
                    <span className={`flex items-center gap-1 text-sm ${status.ok ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {status.ok ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                      {status.label}
                    </span>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" title="Editar perfil" onClick={() => startEdit(profile)}>
                      <Edit3 className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" title={profile.enabled ? 'Desativar perfil' : 'Ativar perfil'} onClick={() => toggleEnabled(profile)}>
                      <Power className={`h-4 w-4 ${profile.enabled ? 'text-emerald-400' : 'text-zinc-500'}`} />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="space-y-1">
      <span className="text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

function NumberField({ label, value, min, onChange }: { label: string; value: number; min: number; onChange: (value: number) => void }) {
  return (
    <Field label={label}>
      <Input type="number" min={min} value={value} onChange={(event) => onChange(Number(event.target.value) || min)} />
    </Field>
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <Field label={label}>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 text-sm"
      >
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </Field>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <Switch checked={checked} onCheckedChange={onChange} />
      {label}
    </label>
  );
}
