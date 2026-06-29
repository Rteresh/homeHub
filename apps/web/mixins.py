from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Доступ только для staff/superuser — ops-разделы (логи, скрипты)."""

    def test_func(self):
        user = self.request.user
        return user.is_active and (user.is_staff or user.is_superuser)
