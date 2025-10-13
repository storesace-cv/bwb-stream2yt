# Windows Service Execution Analysis

## Current Behavior
- The Windows deployment currently launches the application via a console host.
- Two processes (PIDs) are observed: the console host and the application itself.
- Because the program does not ship with a GUI, the visible console window is primarily an operational artifact rather than a user-facing feature.

## Proposal: Add a Windows Service Wrapper
- Introduce a second launcher tailored for running the application as a Windows service while keeping the existing console-based launcher for interactive scenarios.
- Running as a service would collapse execution into a single PID (the service host) and hide the console window from end users.
- Services can be configured for automatic startup, enabling the application to run without an interactive login.

## Considerations
1. **Operational Requirements**
   - The service must register with the Windows Service Control Manager (SCM) and implement the lifecycle callbacks (`Start`, `Stop`, `Pause`, `Continue`) expected by SCM.
   - Logging and observability should not rely on an interactive console; redirect output to files or centralized logging.

2. **Configuration Management**
   - Provide a configuration path accessible to the service context (e.g., via files in `%ProgramData%` or the registry) since user-specific locations may not be available before login.
   - Ensure credentials or API keys used by the application are stored securely and accessible under the service account.

3. **Deployment Strategy**
   - Ship an installer or scripted setup that can register/unregister the service (using `sc.exe` or PowerShell).
   - Offer start/stop/status scripts for administrators who prefer command-line control.

4. **Resource Access**
   - Verify that any hardware or network resources required by the application are accessible from the service account, especially if the current console launcher assumes user-level permissions.

5. **Fallback and Support**
   - Retain the existing console launcher for diagnostics and scenarios where interactive feedback is helpful.
   - Document how to switch between console and service modes to minimize support friction.

## Conclusion
Running the application as a Windows service is feasible and would streamline the user experience by hiding the console window and allowing execution without login. The primary effort lies in building a dedicated service wrapper, handling lifecycle events, and adjusting deployment and logging practices accordingly.

## Implementation Notes
- `primary-windows/src/windows_service.py` implements the Windows service entrypoint on top of the existing streaming loop.
- `stream_to_youtube.py` now expõe *helpers* públicos (`start_streaming_instance`, `stop_streaming_instance`, `stop_active_worker`) usados pelo wrapper para iniciar/parar o worker no mesmo processo.
- Novas variáveis de ambiente (`BWB_ENV_DIR`, `BWB_ENV_FILE`, `BWB_ENV_PATH`) permitem apontar o `.env` para um diretório acessível pelo serviço.
- O README do módulo primário documenta como instalar, iniciar e remover o serviço via `python windows_service.py` e como configurar o ambiente para execução headless.
