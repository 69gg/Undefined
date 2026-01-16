import json
import logging
import importlib.util
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Callable, Awaitable

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, tools_dir: str | Path | None = None):
        if tools_dir is None:
            # Default to the directory where this file is located
            self.tools_dir = Path(__file__).parent
        else:
            self.tools_dir = Path(tools_dir)
        
        self._tools_schema: List[Dict[str, Any]] = []
        self._tools_handlers: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]]] = {}
        self.load_tools()

    def load_tools(self) -> None:
        """Discovers and loads tools from the tools directory."""
        self._tools_schema = []
        self._tools_handlers = {}
        
        if not self.tools_dir.exists():
            logger.warning(f"Tools directory does not exist: {self.tools_dir}")
            return

        for item in self.tools_dir.iterdir():
            if item.is_dir() and not item.name.startswith('_'):
                self._load_tool_from_dir(item)
        
        tool_names = list(self._tools_handlers.keys())
        logger.info(f"Successfully loaded {len(self._tools_schema)} tools: {', '.join(tool_names)}")

    def _load_tool_from_dir(self, tool_dir: Path) -> None:
        """Loads a single tool from a directory."""
        config_path = tool_dir / "config.json"
        handler_path = tool_dir / "handler.py"

        if not config_path.exists() or not handler_path.exists():
            return

        # Load Configuration
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Basic validation
            if "name" not in config.get("function", {}):
                logger.error(f"Invalid tool config in {tool_dir}: missing function.name")
                return
            
            tool_name = config["function"]["name"]
            
        except Exception as e:
            logger.error(f"Failed to load tool config from {tool_dir}: {e}")
            return

        # Load Handler
        try:
            spec = importlib.util.spec_from_file_location(f"tools.{tool_name}", handler_path)
            if spec is None or spec.loader is None:
                logger.error(f"Failed to load tool handler spec from {handler_path}")
                return
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if not hasattr(module, "execute"):
                logger.error(f"Tool handler in {tool_dir} missing 'execute' function")
                return
            
            self._tools_schema.append(config)
            self._tools_handlers[tool_name] = module.execute
            
        except Exception as e:
            logger.error(f"Failed to load tool handler from {tool_dir}: {e}")

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """Returns the list of tool definitions for the AI model."""
        return self._tools_schema

    async def execute_tool(self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Executes a tool by name."""
        handler = self._tools_handlers.get(tool_name)
        if not handler:
            return f"Tool not found: {tool_name}"
        
        try:
            # Check if the handler is a coroutine
            if asyncio.iscoroutinefunction(handler):
                result = await handler(args, context)
            else:
                # We expect tools to be async, but support sync just in case
                # Note: our type hint says Awaitable, so this is just for safety
                result = handler(args, context)
            
            return str(result)
        except Exception as e:
            logger.exception(f"Error executing tool {tool_name}")
            return f"Error executing tool {tool_name}: {str(e)}"
