/**
 * settings.js — Yönetim ekranı (sadece admin): kullanıcı CRUD + audit log.
 */
const Settings = {
  users: [],

  async loadUsers() {
    let data;
    try { data = await App.api('/api/admin/users'); } catch (e) { return; }
    Settings.users = data.items;
    const roleBadge = r => ({
      admin:    '<span class="badge text-bg-danger">Admin</span>',
      operator: '<span class="badge text-bg-warning text-dark">Operatör</span>',
      viewer:   '<span class="badge text-bg-secondary">Görüntüleyici</span>',
    }[r] || r);
    document.getElementById('userBody').innerHTML = data.items.map(u => '<tr>' +
      '<td><strong>' + App.esc(u.username) + '</strong></td>' +
      '<td>' + App.esc(u.full_name || '—') + '</td>' +
      '<td>' + App.esc(u.email || '—') + '</td>' +
      '<td>' + roleBadge(u.role) + '</td>' +
      '<td>' + (u.is_ldap ? 'LDAP/AD' : 'Lokal') + '</td>' +
      '<td class="small">' + App.fmtDate(u.last_login) + '</td>' +
      '<td>' + (u.is_active
        ? '<span class="badge text-bg-success">Aktif</span>'
        : '<span class="badge text-bg-secondary">Pasif</span>') + '</td>' +
      '<td class="text-end">' +
      '<button class="btn btn-sm btn-outline-secondary" onclick="Settings.openUserModal(' + u.id + ')">' +
      '<i class="bi bi-pencil"></i></button> ' +
      '<button class="btn btn-sm btn-outline-' + (u.is_active ? 'danger' : 'success') + '" ' +
      'title="' + (u.is_active ? 'Pasifleştir' : 'Aktifleştir') + '" ' +
      'onclick="Settings.toggleActive(' + u.id + ',' + !u.is_active + ')">' +
      '<i class="bi bi-' + (u.is_active ? 'person-x' : 'person-check') + '"></i></button></td></tr>').join('');
  },

  openUserModal(id = null) {
    const u = id ? Settings.users.find(x => x.id === id) : null;
    document.getElementById('umTitle').textContent = u ? 'Kullanıcıyı Düzenle' : 'Kullanıcı Ekle';
    document.getElementById('umId').value = u ? u.id : '';
    document.getElementById('umUsername').value = u ? u.username : '';
    document.getElementById('umUsername').disabled = !!u;   // kullanıcı adı değişmez
    document.getElementById('umFullName').value = u ? (u.full_name || '') : '';
    document.getElementById('umEmail').value = u ? (u.email || '') : '';
    document.getElementById('umRole').value = u ? u.role : 'viewer';
    document.getElementById('umPassword').value = '';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('userModal')).show();
  },

  async saveUser() {
    const id = document.getElementById('umId').value;
    const payload = {
      username: document.getElementById('umUsername').value.trim(),
      full_name: document.getElementById('umFullName').value.trim(),
      email: document.getElementById('umEmail').value.trim(),
      role: document.getElementById('umRole').value,
      password: document.getElementById('umPassword').value,
    };
    if (!payload.username) { App.toast('Kullanıcı adı zorunludur', 'warning'); return; }
    if (!id && !payload.password) { App.toast('Yeni kullanıcı için parola zorunludur', 'warning'); return; }
    try {
      if (id) await App.api('/api/admin/users/' + id, {method: 'PATCH', body: payload});
      else    await App.api('/api/admin/users', {method: 'POST', body: payload});
      App.toast('Kullanıcı kaydedildi');
      bootstrap.Modal.getInstance(document.getElementById('userModal')).hide();
      Settings.loadUsers();
    } catch (e) { /* hata gösterildi */ }
  },

  async toggleActive(id, active) {
    try {
      await App.api('/api/admin/users/' + id, {method: 'PATCH', body: {is_active: active}});
      App.toast(active ? 'Kullanıcı aktifleştirildi' : 'Kullanıcı pasifleştirildi');
      Settings.loadUsers();
    } catch (e) { /* hata gösterildi */ }
  },

  async loadAudit() {
    let data;
    try { data = await App.api('/api/admin/audit'); } catch (e) { return; }
    document.getElementById('auditBody').innerHTML = data.items.length
      ? data.items.map(l => '<tr>' +
          '<td class="text-nowrap small">' + App.fmtDate(l.timestamp) + '</td>' +
          '<td>' + App.esc(l.username) + '</td>' +
          '<td><code>' + App.esc(l.action) + '</code></td>' +
          '<td class="small">' + App.esc(l.detail || '') + '</td>' +
          '<td class="small">' + App.esc(l.ip_address || '') + '</td></tr>').join('')
      : '<tr><td colspan="5" class="text-muted p-3">Kayıt yok.</td></tr>';
  },
};

Settings.loadUsers();
Settings.loadAudit();
