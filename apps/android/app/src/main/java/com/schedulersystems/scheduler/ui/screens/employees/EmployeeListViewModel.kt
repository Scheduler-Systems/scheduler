package com.schedulersystems.scheduler.ui.screens.employees

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.Role
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class EmployeeListState(
    val isLoading: Boolean = true,
    val employees: List<Employee> = emptyList(),
    val scheduleName: String = "",
    val scheduleId: String = "",
    val error: String? = null
)

data class AddEmployeeState(
    val email: String = "",
    val phone: String = "",
    val name: String = "",
    val isAdding: Boolean = false,
    val isAdded: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class EmployeeListViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository
) : ViewModel() {

    private val _state = MutableStateFlow(EmployeeListState())
    val state: StateFlow<EmployeeListState> = _state.asStateFlow()

    private val _addState = MutableStateFlow(AddEmployeeState())
    val addState: StateFlow<AddEmployeeState> = _addState.asStateFlow()

    fun loadEmployees(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            // The schedule is fetched for its display name (and existence check); the
            // roster comes from its own endpoint (not embedded in the schedule doc).
            val schedule = scheduleRepository.getScheduleById(scheduleId)
            if (schedule == null) {
                _state.update { it.copy(isLoading = false, error = "Schedule not found") }
                return@launch
            }
            val employees = scheduleRepository.getEmployees(scheduleId)
            _state.update {
                it.copy(
                    isLoading = false,
                    employees = employees,
                    scheduleName = schedule.name,
                    scheduleId = scheduleId,
                    error = null
                )
            }
        }
    }

    // Reset the add-employee form (called when the dialog opens/closes) so a prior
    // success (isAdded=true) doesn't immediately re-close a freshly opened dialog.
    fun dismissAdd() {
        _addState.value = AddEmployeeState()
    }

    fun setEmail(email: String) {
        _addState.update { it.copy(email = email) }
    }

    fun setName(name: String) {
        _addState.update { it.copy(name = name) }
    }

    fun setPhone(phone: String) {
        _addState.update { it.copy(phone = phone) }
    }

    fun addEmployee(scheduleId: String) {
        viewModelScope.launch {
            _addState.update { it.copy(isAdding = true, error = null) }
            val s = _addState.value
            val employee = Employee(
                id = java.util.UUID.randomUUID().toString(),
                name = s.name,
                email = s.email.takeIf { it.isNotBlank() },
                phone = s.phone.takeIf { it.isNotBlank() },
                role = Role.EMPLOYEE,
                priorityMap = emptyMap()
            )
            val result = scheduleRepository.addEmployee(scheduleId, employee)
        result.fold(
            onSuccess = {
                _addState.update { it.copy(isAdding = false, isAdded = true, email = "", name = "", phone = "") }
                loadEmployees(scheduleId)
            },
            onFailure = { ex -> _addState.update { it.copy(isAdding = false, error = ex.message) } }
        )
        }
    }

    fun removeEmployee(scheduleId: String, employeeId: String) {
        viewModelScope.launch {
            val result = scheduleRepository.removeEmployee(scheduleId, employeeId)
            result.fold(
                onSuccess = { loadEmployees(scheduleId) },
                onFailure = { ex -> _state.update { it.copy(error = ex.message) } }
            )
        }
    }
}
